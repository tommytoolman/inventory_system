# scripts/vr/seed_vr_from_reverb_mapping.py
import os, sys, csv, argparse, asyncio, math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.database import async_session
from app.models.platform_common import PlatformCommon, ListingStatus, SyncStatus
from app.models.vr import VRListing
from app.services.vintageandrare.client import VintageAndRareClient

load_dotenv()
DEFAULT_MAPPING_FILE = "scripts/reverb_to_vr.csv"
SKIP_TOKEN = "#N/A"

def _clean_vr_value(v):
    if v is None:
        return None
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, str) and v.strip().upper() in {"NAN", "NA", "#N/A", "NULL", ""}:
        return None
    return v

def _sanitize_vr_payload(d: dict) -> dict:
    return {k: _clean_vr_value(v) for k, v in d.items()} if isinstance(d, dict) else {}

def utc_naive_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def read_mapping(path: str, skip_token: str = SKIP_TOKEN, limit: Optional[int] = None) -> Tuple[List[Tuple[str,str]], Dict]:
    rows: List[Tuple[str,str]] = []
    seen_reverb = set()
    seen_vr = set()
    dup_reverb = set()
    dup_vr = set()
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header_map = {h.lower(): h for h in (reader.fieldnames or [])}
        required = {"reverb_id","vr_id"}
        missing = required - set(header_map.keys())
        if missing:
            print(f"❌ Missing required columns: {missing}")
            sys.exit(1)
        for row in reader:
            rid = str(row[header_map["reverb_id"]]).strip()
            vid = str(row[header_map["vr_id"]]).strip()
            if not rid:
                continue
            if vid == "" or vid == skip_token:
                # Intentionally no VR listing
                continue
            if rid in seen_reverb: dup_reverb.add(rid)
            else: seen_reverb.add(rid)
            if vid in seen_vr: dup_vr.add(vid)
            else: seen_vr.add(vid)
            rows.append((rid, vid))
            if limit and len(rows) >= limit:
                break
    stats = {
        "mapping_rows_used": len(rows),
        "duplicate_reverb_ids": sorted(dup_reverb),
        "duplicate_vr_ids": sorted(dup_vr),
    }
    return rows, stats

async def fetch_active_vr_lookup(username: str, password: str) -> Dict[str, dict]:
    """
    Download inventory via client, filter to active (product_sold == 'no'),
    return dict keyed by vr_listing_id (or 'vr_listing_id' / 'vr_id' column fallback).
    """
    client = VintageAndRareClient(username=username, password=password)
    print("🔐 Authenticating with V&R...")
    if not await client.authenticate():
        raise RuntimeError("Failed to authenticate with V&R")
    print("📊 Downloading full inventory CSV...")
    df = await client.download_inventory_dataframe(save_to_file=False, output_path=None)
    if df is None or df.empty:
        print("❌ No V&R inventory data received")
        return {}
    # Determine id column
    id_col = None
    for candidate in ("product_id","vr_listing_id","listing_id","id"):
        if candidate in df.columns:
            id_col = candidate
            break
    if not id_col:
        print("❌ Could not find a VR listing id column in CSV")
        return {}
    live_df = df[df.get("product_sold","yes") == "no"]
    print(f"🟢 Active listings in remote feed: {len(live_df)}")
    lookup = {}
    for _, row in live_df.iterrows():
        vrid = str(row[id_col]).strip()
        if not vrid:
            continue
        lookup[vrid] = row.to_dict()
    # Cleanup temp files (if any)
    client.cleanup_temp_files()
    return lookup

async def get_product_id_from_reverb_external(session, reverb_external_id: str) -> Optional[int]:
    q = select(PlatformCommon.product_id).where(
        PlatformCommon.platform_name == "reverb",
        PlatformCommon.external_id == reverb_external_id
    )
    res = await session.execute(q)
    return res.scalar_one_or_none()

async def upsert_platform_common_vr(session, product_id: int, vr_id: str) -> Tuple[int,bool]:
    q = select(PlatformCommon).where(
        PlatformCommon.platform_name == "vr",
        PlatformCommon.external_id == vr_id
    )
    res = await session.execute(q)
    existing = res.scalar_one_or_none()
    if existing:
        return existing.id, False
    now = utc_naive_now()
    pc = PlatformCommon(
        product_id=product_id,
        platform_name="vr",
        external_id=vr_id,
        status=ListingStatus.ACTIVE.value,
        sync_status=SyncStatus.SYNCED.value,
        last_sync=now
    )
    session.add(pc)
    await session.flush()
    return pc.id, True

async def upsert_vr_listing(session, platform_id: int, vr_id: str, vr_data: dict) -> bool:
    q = select(VRListing).where(VRListing.platform_id == platform_id)
    res = await session.execute(q)
    existing = res.scalar_one_or_none()
    if existing:
        return False
    now = utc_naive_now()
    # Infer price_notax if present
    price_notax = None
    for k in ("product_price","price_notax","price"):
        if isinstance(vr_data, dict) and k in vr_data:
            try:
                val = vr_data[k]
                if val not in ("", None):
                    price_notax = float(val)
            except Exception:
                pass
            break
    vr_state = "active"
    
    
    listing = VRListing(
        platform_id=platform_id,
        vr_listing_id=vr_id,
        vr_state=vr_state,
        inventory_quantity=1,
        price_notax=price_notax,
        created_at=now,
        updated_at=now,
        last_synced_at=now,
        extended_attributes=_sanitize_vr_payload(vr_data)
    )
    session.add(listing)
    return True

async def run(
    mapping_file: str,
    username: Optional[str],
    password: Optional[str],
    dry_run: bool,
    limit: Optional[int],
    active_only: bool,
    allow_no_vr_data: bool
):
    """
    Seed VR platform_common + vr_listings from a Reverb→VR mapping without creating Products.

    Args:
        mapping_file: CSV with columns reverb_id, vr_id (#N/A rows skipped)
        username/password: V&R credentials (optional; pulled from env if missing)
        dry_run: If True, no DB writes
        limit: Process only first N usable mapping rows
        active_only: Only create rows if vr_id present in live active feed
        allow_no_vr_data: If True and creds missing, proceed without active feed (active_only still enforced = no effect)
    """
    # Fallback to env credentials if not provided
    if not username:
        username = os.getenv("VINTAGE_AND_RARE_USERNAME")
    if not password:
        password = os.getenv("VR_PASSWORD") or os.getenv("VINTAGE_AND_RARE_PASSWORD")

    creds_available = bool(username and password)

    print(f"📄 Mapping file: {mapping_file}")
    rows, map_stats = read_mapping(mapping_file, limit=limit)
    print(f"🔢 Usable mapping rows: {map_stats['mapping_rows_used']}")
    if map_stats["duplicate_reverb_ids"]:
        print(f"⚠️ Duplicate reverb_ids (first 5): {map_stats['duplicate_reverb_ids'][:5]}")
    if map_stats["duplicate_vr_ids"]:
        print(f"⚠️ Duplicate vr_ids (first 5): {map_stats['duplicate_vr_ids'][:5]}")

    # Fetch active VR inventory (or skip)
    if active_only:
        if creds_available:
            vr_active_lookup = await fetch_active_vr_lookup(username, password)
            print(f"📥 Active VR listings fetched: {len(vr_active_lookup)}")
        else:
            if allow_no_vr_data:
                print("⚠️ No V&R credentials; proceeding WITHOUT active feed (all treated as not active).")
                vr_active_lookup = {}
            else:
                print("❌ No credentials and --allow-no-vr-data not set. Aborting.")
                return
    else:
        if creds_available:
            # Optional: still fetch to enrich even if not filtering
            vr_active_lookup = await fetch_active_vr_lookup(username, password)
            print(f"📥 VR listings fetched (not filtering): {len(vr_active_lookup)}")
        else:
            vr_active_lookup = {}
            if not allow_no_vr_data:
                print("⚠️ Proceeding without VR data (no credentials).")

    created_pc = existing_pc = 0
    created_vr = existing_vr = 0
    skipped_not_active = 0
    skipped_missing_reverb = 0
    processed = 0

    async with async_session() as session:
        for reverb_id, vr_id in rows:
            processed += 1

            # Find product via existing Reverb linkage
            product_id = await get_product_id_from_reverb_external(session, reverb_id)
            if not product_id:
                skipped_missing_reverb += 1
                print(f"❌ No product/platform_common for reverb_id={reverb_id}; skip vr_id={vr_id}")
                continue

            vr_payload = vr_active_lookup.get(vr_id)

            if active_only and not vr_payload:
                skipped_not_active += 1
                continue

            if dry_run:
                continue

            # Upsert platform_common (vr)
            pc_id, pc_created = await upsert_platform_common_vr(session, product_id, vr_id)
            if pc_created:
                created_pc += 1
            else:
                existing_pc += 1

            # Upsert vr_listings
            added = await upsert_vr_listing(session, pc_id, vr_id, vr_payload or {})
            if added:
                created_vr += 1
            else:
                existing_vr += 1

            if processed % 100 == 0 and not dry_run:
                await session.commit()
                print(f"💾 Commit at {processed} rows...")

        if not dry_run:
            await session.commit()

    print("\n===== Summary =====")
    print(f"Processed mapping rows:        {processed}")
    print(f"PlatformCommon created (vr):   {created_pc}")
    print(f"PlatformCommon existing:       {existing_pc}")
    print(f"VR listings created:           {created_vr}")
    print(f"VR listings existing:          {existing_vr}")
    print(f"Skipped (not active):          {skipped_not_active}")
    print(f"Skipped (no reverb match):     {skipped_missing_reverb}")
    print(f"Dry run:                       {dry_run}")
    print(f"Active-only mode:              {active_only}")
    print(f"Creds available:               {creds_available}")
    print("✅ Done.")

def parse_args():
    p = argparse.ArgumentParser(
        description="Seed VR platform entries from Reverb→VR mapping (active VR listings only)."
    )
    p.add_argument("--mapping-file", default=DEFAULT_MAPPING_FILE)
    # No longer required – optional overrides
    p.add_argument("--username", help="V&R username (env: VINTAGE_AND_RARE_USERNAME)")
    p.add_argument("--password", help="V&R password (env: VR_PASSWORD or VINTAGE_AND_RARE_PASSWORD)")
    p.add_argument("--dry-run", action="store_true", help="Simulate only; no DB writes")
    p.add_argument("--limit", type=int, help="Process only first N mapping rows")
    p.add_argument("--no-active-only", action="store_true", help="Allow creation even if vr_id not live now")
    p.add_argument("--allow-no-vr-data", action="store_true",
                   help="Proceed without fetching live VR data (no username/password found)")
    return p.parse_args()

def main():
    args = parse_args()
    try:
        asyncio.run(run(
            mapping_file=args.mapping_file,
            username=args.username,
            password=args.password,
            dry_run=args.dry_run,
            limit=args.limit,
            active_only=not args.no_active_only,
            allow_no_vr_data=args.allow_no_vr_data
        ))
    except KeyboardInterrupt:
        print("\nInterrupted.")
    except SQLAlchemyError as e:
        print(f"DB Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()