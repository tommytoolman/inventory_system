import os, sys, csv, json, argparse, asyncio, re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session
from app.models.product import Product, ProductStatus, ProductCondition
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.ebay import EbayListing
from app.services.ebay.trading import EbayTradingLegacyAPI

load_dotenv()

DEFAULT_MAPPING_FILE = "scripts/reverb_to_ebay.csv"     # columns: reverb_id, ebay_id
DEFAULT_EBAY_CSV      = "data/EBAY_LISTINGS_ACTIVE_FLAT.csv"  # your exported eBay active CSV
SKIP_TOKEN = "#N/A"

YEAR_RE = re.compile(r'\b(19|20)\d{2}\b')

ENRICH_BATCH = 40


# ---------------- Shared helpers ----------------

def safe_decimal(val) -> Optional[Decimal]:
    if val is None or val == "" or str(val).upper() in ("NAN","NULL"):
        return None
    try:
        return Decimal(str(val))
    except (InvalidOperation, ValueError):
        return None

def safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return None

def utc_now_naive():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def parse_ebay_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Parse eBay datetime string (e.g., '2025-08-07T08:52:39.000Z') into a naive Python datetime object.
    """
    if not dt_str:
        return None
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)  # Convert to naive datetime
    except ValueError:
        return None

def flatten_ebay_listing(ls: Dict) -> Dict:
    """Extract stable fields for analysis/import."""
    out = {
        "ItemID": ls.get("ItemID"),
        "Title": ls.get("Title"),
        "SKU": ls.get("SKU"),
        "ListingStatus": ls.get("SellingStatus", {}).get("ListingStatus") or ls.get("ListingStatus"),
        "Quantity": ls.get("Quantity"),
        "QuantityAvailable": ls.get("QuantityAvailable"),
        "QuantitySold": (ls.get("SellingStatus", {}) or {}).get("QuantitySold"),
        "CurrentPrice": (ls.get("SellingStatus", {}).get("CurrentPrice", {}) or {}).get("#text") 
                         or (ls.get("CurrentPrice", {}) or {}).get("#text"),
        "Currency": (ls.get("SellingStatus", {}).get("CurrentPrice", {}) or {}).get("currencyID")
                    or (ls.get("CurrentPrice", {}) or {}).get("currencyID"),
        "PrimaryCategoryID": (ls.get("PrimaryCategory", {}) or {}).get("CategoryID"),
        "PrimaryCategoryName": (ls.get("PrimaryCategory", {}) or {}).get("CategoryName"),
        "ConditionID": ls.get("ConditionID"),
        "ConditionDisplayName": ls.get("ConditionDisplayName"),
        "ViewItemURL": ls.get("ListingDetails", {}).get("ViewItemURL") or ls.get("ViewItemURL"),
    }
    return out

#  ---------------- API fetch & enrichment ----------------

async def fetch_live_ebay(api: EbayTradingLegacyAPI, *, active_only: bool = True) -> List[Dict]:
    """
    Fetch raw active (and optionally sold/unsold) listings via bulk Trading API call.
    Returns raw summary listing dicts exactly as returned (no mutation).
    """
    listings_resp = await api.get_all_selling_listings(
        include_active=True,
        include_sold=not active_only,
        include_unsold=False,
        include_details=False
    )
    return list(listings_resp.get("active", []))

async def enrich_item_details(api: EbayTradingLegacyAPI, item_ids: List[str], batch: int = 40) -> Dict[str, Dict]:
    """
    Fetch per-item GetItem details; returns map item_id -> detail dict (empty dict on failure).
    """
    enriched: Dict[str, Dict] = {}
    for i in range(0, len(item_ids), batch):
        sub = item_ids[i:i+batch]
        tasks = [api.get_item_details(iid) for iid in sub]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for iid, res in zip(sub, results):
            enriched[iid] = res if isinstance(res, dict) else {}
    return enriched

def parse_gallery_url(picture_json: str) -> Optional[str]:
    if not picture_json:
        return None
    try:
        obj = json.loads(picture_json)
        return obj.get("GalleryURL")
    except Exception:
        return None

def detect_year(title: str) -> Optional[int]:
    if not title:
        return None
    m = YEAR_RE.search(title)
    if m:
        try:
            return int(m.group())
        except:
            return None
    return None

def split_brand_model(title: str) -> Tuple[Optional[str], Optional[str]]:
    if not title:
        return None, None
    parts = title.strip().split(" ",1)
    if not parts:
        return None, None
    brand = parts[0].strip()
    model = parts[1].strip() if len(parts) > 1 else None
    return brand, model

# ---------------- Mapping / Analysis ----------------

def read_mapping(path: str, limit: Optional[int]) -> List[Tuple[str, str]]:
    """
    Returns list of (reverb_id, ebay_id) skipping blank / SKIP_TOKEN
    """
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        hdr = {h.lower(): h for h in (r.fieldnames or [])}
        required = {"reverb_id", "ebay_id"}
        if not required.issubset(hdr):
            print("❌ Mapping requires headers: reverb_id, ebay_id")
            sys.exit(1)
        for line in r:
            rid = str(line[hdr["reverb_id"]]).strip()
            eid = str(line[hdr["ebay_id"]]).strip()
            if not rid or not eid or eid == SKIP_TOKEN:
                continue
            rows.append((rid, eid))
            if limit and len(rows) >= limit:
                break
    return rows

async def analyze(mapping_rows, ebay_rows):
    mapping_set = {eid for _,eid in mapping_rows}
    reverb_by_ebay = {eid: rid for rid,eid in mapping_rows}

    ebay_by_id = {row.get("ItemID"): row for row in ebay_rows if row.get("ItemID")}
    ebay_ids_csv = set(ebay_by_id.keys())

    mapped_existing_csv = mapping_set & ebay_ids_csv
    mapping_unresolved_ebay = mapping_set - ebay_ids_csv    # mapping references ebay_id not in CSV
    ebay_only = ebay_ids_csv - mapping_set                  # eBay item not in mapping file

    print("=== ANALYSIS ===")
    print(f"Total mapping usable rows : {len(mapping_rows)}")
    print(f"Total eBay CSV rows       : {len(ebay_rows)}")
    print(f"Mapped & present in CSV   : {len(mapped_existing_csv)}")
    print(f"Mapping -> missing in CSV : {len(mapping_unresolved_ebay)}")
    print(f"eBay only (orphans)       : {len(ebay_only)}")

    # Sample a few
    if mapping_unresolved_ebay:
        print(f"Sample unresolved mapping ebay_ids: {list(mapping_unresolved_ebay)[:5]}")
    if ebay_only:
        print(f"Sample orphan eBay ItemIDs: {list(ebay_only)[:5]}")

    return {
        "mapped_existing_csv": mapped_existing_csv,
        "mapping_unresolved_ebay": mapping_unresolved_ebay,
        "ebay_only": ebay_only,
        "reverb_by_ebay": reverb_by_ebay,
        "ebay_by_id": ebay_by_id
    }

def read_ebay_csv(path: str) -> List[Dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        r=csv.DictReader(f)
        return [row for row in r]

# ---------------- Normalization ----------------

def normalize_listing(raw: Dict) -> Dict:
    """
    Merge summary + detail raw listing dict into a normalized flat structure
    (no DB objects created here).
    """
    selling = raw.get("SellingStatus") or {}
    listing_details = raw.get("ListingDetails") or {}
    pics = raw.get("PictureDetails") or {}
    profiles = raw.get("SellerProfiles") or {}

    # PictureURLs normalization
    picture_urls = pics.get("PictureURL")
    if isinstance(picture_urls, str):
        picture_urls = [picture_urls]
    elif not isinstance(picture_urls, list):
        picture_urls = []

    specifics = raw.get("ItemSpecifics")
    # Keep specifics raw; caller can transform later if needed
    if specifics in ("", {}, []):
        specifics = None

    def _money(node):
        if not isinstance(node, dict):
            return None
        return safe_decimal(node.get("#text"))

    current_price = _money(selling.get("CurrentPrice") or {})
    buy_it_now = _money(raw.get("BuyItNowPrice") or {})

    return {
        "ItemID": raw.get("ItemID"),
        "Title": raw.get("Title"),
        "ListingType": raw.get("ListingType"),
        "ListingStatus": (selling.get("ListingStatus") or raw.get("ListingStatus") or "Active"),
        "Quantity": safe_int(raw.get("Quantity")),
        "QuantityAvailable": safe_int(raw.get("QuantityAvailable")),
        "QuantitySold": safe_int(selling.get("QuantitySold")),
        "Price": current_price or buy_it_now,
        "Currency": (selling.get("CurrentPrice") or {}).get("@currencyID")
                    or (raw.get("BuyItNowPrice") or {}).get("@currencyID"),
        "PrimaryCategoryID": (raw.get("PrimaryCategory") or {}).get("CategoryID"),
        "PrimaryCategoryName": (raw.get("PrimaryCategory") or {}).get("CategoryName"),
        "SecondaryCategoryID": (raw.get("SecondaryCategory") or {}).get("CategoryID"),
        "SecondaryCategoryName": (raw.get("SecondaryCategory") or {}).get("CategoryName"),
        "StartTime": listing_details.get("StartTime"),
        "EndTime": listing_details.get("EndTime"),
        "ViewItemURL": listing_details.get("ViewItemURL"),
        "ConditionID": raw.get("ConditionID"),
        "ConditionDisplayName": raw.get("ConditionDisplayName"),
        "GalleryURL": pics.get("GalleryURL") or (picture_urls[0] if picture_urls else None),
        "PictureURLs": picture_urls,
        "ItemSpecifics": specifics,
        "PaymentProfileID": (profiles.get("SellerPaymentProfile") or {}).get("PaymentProfileID"),
        "ReturnProfileID": (profiles.get("SellerReturnProfile") or {}).get("ReturnProfileID"),
        "ShippingProfileID": (profiles.get("SellerShippingProfile") or {}).get("ShippingProfileID"),
        "WatchCount": safe_int(raw.get("WatchCount")),
        "Raw": raw  # full snapshot retained
    }

async def get_product_id_from_reverb(session, reverb_id: str) -> Optional[int]:
    q = select(PlatformCommon.product_id).where(
        PlatformCommon.platform_name=='reverb',
        PlatformCommon.external_id==reverb_id
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()

async def get_platform_common(session, product_id: int, platform: str) -> Optional[PlatformCommon]:
    q = select(PlatformCommon).where(
        PlatformCommon.product_id==product_id,
        PlatformCommon.platform_name==platform
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()

async def get_ebay_listing_by_platform(session, platform_id: int) -> Optional[EbayListing]:
    q = select(EbayListing).where(EbayListing.platform_id==platform_id)
    res = await session.execute(q)
    return res.scalar_one_or_none()

async def get_platform_common_by_external(session, platform: str, external: str) -> Optional[PlatformCommon]:
    q = select(PlatformCommon).where(
        PlatformCommon.platform_name==platform,
        PlatformCommon.external_id==external
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()

def extract_price(row: Dict) -> Optional[Decimal]:
    # Primary 'price' column else BuyItNowPrice_#text
    return safe_decimal(
        row.get("price") or
        row.get("BuyItNowPrice_#text")
    )

# ---------------- Construction of DB model ----------------

def build_ebay_listing(platform_id: int, row: Dict) -> EbayListing:
    """
    Convert normalized listing row into EbayListing ORM instance.
    Assumes row already normalized by normalize_listing.
    """
    status_map = {
        "active": ListingStatus.ACTIVE.value,
        "completed": ListingStatus.SOLD.value,
        "ended": ListingStatus.ENDED.value,
        "unsold": ListingStatus.ENDED.value,
        "sold": ListingStatus.SOLD.value,
        "cancelled": ListingStatus.ENDED.value
    }
    raw_status = (row.get("ListingStatus") or "").strip().lower()
    listing_status = status_map.get(raw_status, ListingStatus.ACTIVE.value)

    price = row.get("Price") or Decimal("0")
    qty = row.get("Quantity") or 1
    qty_avail = row.get("QuantityAvailable") or qty
    qty_sold = row.get("QuantitySold") or 0

    picture_urls = row.get("PictureURLs") or []
    if isinstance(picture_urls, str):
        picture_urls = [picture_urls]

    item_specifics = row.get("ItemSpecifics")
    if item_specifics in ([], {}, ""):
        item_specifics = None

    # Include watch_count and other extra fields in listing_data
    listing_data = row.copy()
    listing_data["watch_count"] = row.get("WatchCount")

    # Sanitize listing_data to ensure all Decimal values are converted to float
    def sanitize_for_json(data):
        if isinstance(data, Decimal):
            return float(data)
        elif isinstance(data, dict):
            return {k: sanitize_for_json(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [sanitize_for_json(v) for v in data]
        return data

    sanitized_listing_data = sanitize_for_json(listing_data)

    return EbayListing(
        platform_id=platform_id,
        ebay_item_id=row.get("ItemID"),
        title=row.get("Title"),
        format=(row.get("ListingType") or "").upper() or None,
        listing_status=listing_status,
        price=price,
        quantity=qty,
        quantity_available=qty_avail,
        quantity_sold=qty_sold,
        ebay_category_id=row.get("PrimaryCategoryID"),
        ebay_category_name=row.get("PrimaryCategoryName"),
        ebay_second_category_id=row.get("SecondaryCategoryID"),
        start_time=parse_ebay_datetime(row.get("StartTime")),  # Ensure naive datetime
        end_time=parse_ebay_datetime(row.get("EndTime")),      # Ensure naive datetime
        listing_url=row.get("ViewItemURL"),
        ebay_condition_id=row.get("ConditionID"),
        condition_display_name=row.get("ConditionDisplayName"),
        gallery_url=row.get("GalleryURL"),
        picture_urls=picture_urls,
        item_specifics=item_specifics,
        payment_policy_id=row.get("PaymentProfileID"),
        return_policy_id=row.get("ReturnProfileID"),
        shipping_policy_id=row.get("ShippingProfileID"),
        listing_data=sanitized_listing_data  # Use sanitized data
    )

# ---------------- Import orchestration ----------------

async def import_data(analysis: Dict, *, include_orphans: bool, dry_run: bool):
    """
    Insert mapped listings (and optional orphans).
    """
    mapped = analysis["mapped_existing_csv"]
    orphans = analysis["ebay_only"]
    reverb_by_ebay = analysis["reverb_by_ebay"]
    ebay_by_id = analysis["ebay_by_id"]

    created_pc = existing_pc = 0
    created_list = existing_list = 0
    created_orphan_products = 0
    skipped_missing_reverb = 0

    async with async_session() as session:
        # Mapped listings
        for eid in mapped:
            row = ebay_by_id[eid]
            reverb_id = reverb_by_ebay.get(eid)
            product_id = await get_product_id_from_reverb(session, reverb_id)
            if not product_id:
                skipped_missing_reverb += 1
                continue

            pc = await get_platform_common_by_external(session, "ebay", eid)
            if not pc:
                pc = PlatformCommon(
                    product_id=product_id,
                    platform_name="ebay",
                    external_id=eid,
                    status=ListingStatus.ACTIVE.value,
                    sync_status=SyncStatus.SYNCED.value,
                    last_sync=utc_now_naive()
                )
                session.add(pc)
                await session.flush()
                created_pc += 1
            else:
                existing_pc += 1

            existing = await get_ebay_listing_by_platform(session, pc.id)
            if existing:
                existing_list += 1
            else:
                session.add(build_ebay_listing(pc.id, row))
                created_list += 1

        # Orphans (optional)
        if include_orphans:
            for eid in orphans:
                row = ebay_by_id[eid]
                brand, model = split_brand_model(row.get("Title") or "")
                year = detect_year(row.get("Title") or "")
                prod = Product(
                    sku=f"EBY-{eid}",
                    brand=brand,
                    model=model,
                    year=year,
                    description="",
                    condition=ProductCondition.GOOD,
                    category=None,
                    base_price=row.get("Price"),
                    status=ProductStatus.ACTIVE
                )
                session.add(prod)
                await session.flush()
                created_orphan_products += 1

                pc = PlatformCommon(
                    product_id=prod.id,
                    platform_name="ebay",
                    external_id=eid,
                    status=ListingStatus.ACTIVE.value,
                    sync_status=SyncStatus.SYNCED.value,
                    last_sync=utc_now_naive()
                )
                session.add(pc)
                await session.flush()
                created_pc += 1

                session.add(build_ebay_listing(pc.id, row))
                created_list += 1

        if dry_run:
            await session.rollback()
            print("Dry run: rolled back.")
        else:
            await session.commit()

    print("=== IMPORT SUMMARY ===")
    print(f"PlatformCommon created       : {created_pc}")
    print(f"PlatformCommon existing      : {existing_pc}")
    print(f"Ebay listings created        : {created_list}")
    print(f"Ebay listings existing       : {existing_list}")
    print(f"Orphan products created      : {created_orphan_products}")
    print(f"Skipped (missing reverb prod): {skipped_missing_reverb}")
    print(f"Dry run                      : {dry_run}")

def parse_args():
    p = argparse.ArgumentParser(description="Seed eBay listings from Reverb→eBay mapping + eBay active CSV.")
    p.add_argument("--mapping-file", default=DEFAULT_MAPPING_FILE, help="CSV with reverb_id,ebay_id")
    p.add_argument("--fetch-live", action="store_true", help="Fetch live active listings via Trading API (ignore --ebay-csv)")
    p.add_argument("--enrich", action="store_true", help="Also call GetItem for details (slower)")
    p.add_argument("--ebay-csv", default=DEFAULT_EBAY_CSV, help="Flat active eBay CSV export")
    p.add_argument("--limit", type=int, help="Limit mapping rows (debug)")
    p.add_argument("--analyze-only", action="store_true", help="Only analyze; no writes")
    p.add_argument("--include-orphans", action="store_true", help="Create products for eBay-only items")
    p.add_argument("--dry-run", action="store_true", help="Run import but rollback at end")
    return p.parse_args()

async def main(args):
    mapping_rows = read_mapping(args.mapping_file, args.limit)
    
    if args.fetch_live:
        print("🔄 Fetching active eBay listings (live)...")
        api = EbayTradingLegacyAPI(sandbox=False)  # Initialize API client
        raw_summary_resp = await fetch_live_ebay(api, active_only=True)  # Fetch active listings
        summary_by_id = {r.get("ItemID"): r for r in raw_summary_resp if r.get("ItemID")}
        item_ids = list(summary_by_id.keys())
        print(f"📦 Retrieved {len(item_ids)} active summary listings")

        details_map = {}
        if args.enrich:
            print("🔍 Enriching with GetItem (detail fetch)...")
            details_map = await enrich_item_details(api, item_ids)

            # Merge detail fields into summary
            for iid, detail in details_map.items():
                if not detail:
                    continue
                base = summary_by_id.get(iid)
                if base:
                    # detail overwrites / augments
                    base.update(detail)

        # Normalize
        normalized_rows = []
        for iid, merged in summary_by_id.items():
            normalized_rows.append(normalize_listing(merged))

        # Persist for inspection
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs("data", exist_ok=True)
        norm_json_path = f"data/ebay_active_normalized_{ts}.json"
        
        def _json_safe(obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return obj

        # Make a serializable copy (keeps DB-origin Decimals in memory if you need them later)
        serializable_rows = []
        for r in normalized_rows:
            serializable_rows.append({
                k: (float(v) if isinstance(v, Decimal) else v)
                for k, v in r.items()
            })

        with open(norm_json_path, "w") as f:
            json.dump(serializable_rows, f, default=_json_safe)
        print(f"💾 Saved normalized JSON: {norm_json_path}")

        # Build a flat CSV for quick inspection (select keys)
        norm_csv_path = f"data/ebay_active_normalized_{ts}.csv"
        field_order = ["ItemID","Title","ListingType","ListingStatus","Price","Currency",
                    "Quantity","QuantityAvailable","QuantitySold",
                    "PrimaryCategoryID","PrimaryCategoryName",
                    "ConditionID","ConditionDisplayName","WatchCount",
                    "StartTime","EndTime","ViewItemURL","GalleryURL"]
        with open(norm_csv_path,"w",newline="",encoding="utf-8") as fcsv:
            w = csv.DictWriter(fcsv, fieldnames=field_order)
            w.writeheader()
            for r in normalized_rows:
                w.writerow({k: r.get(k) for k in field_order})
        print(f"💾 Saved normalized CSV: {norm_csv_path}")

        # For analysis/import we now use normalized_rows
        ebay_rows = normalized_rows
    else:
        ebay_rows = read_ebay_csv(args.ebay_csv)
    
    # Quick field diversity dump (first run only)
    sample_keys = set()
    for r in ebay_rows[:50]:
        sample_keys.update([k for k,v in r.items() if v not in (None,"")])
    print(f"🔍 Non-empty keys in first 50 flattened rows: {sorted(sample_keys)}")
    
    analysis = await analyze(mapping_rows, ebay_rows)

    if args.analyze_only:
        return

    await import_data(
        analysis,
        include_orphans=args.include_orphans,
        dry_run=args.dry_run
    )

if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except SQLAlchemyError as e:
        print(f"DB Error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("Interrupted.")