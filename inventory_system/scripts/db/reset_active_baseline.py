import os
import sys
import asyncio
from sqlalchemy import text
from dotenv import load_dotenv
from app.database import get_session

load_dotenv()

TABLES = [
    "ebay_listings",
    "reverb_listings",
    "vr_listings",
    "shopify_listings",
    "platform_common",
    "products",
]

CONFIRM_TOKEN = "truncate"


def _db_name() -> str:
    url = os.getenv("DATABASE_URL", "")
    if "://" not in url:
        return ""
    tail = url.split("://", 1)[1].split("?", 1)[0]
    return tail.rsplit("/", 1)[-1]


async def _get_counts(session):
    counts = {}
    for t in TABLES:
        res = await session.execute(text(f'SELECT COUNT(*) FROM "{t}"'))
        counts[t] = res.scalar() or 0
    return counts


async def reset_active_baseline() -> None:
    db = _db_name()
    if not db:
        print("❌ DATABASE_URL missing/invalid. Aborting.")
        sys.exit(1)
    if "test" not in db.lower():
        print(f"🚫 Refusing to truncate non-test database '{db}' (must contain 'test').")
        sys.exit(2)

    print("============================================================")
    print(" BASELINE RESET (TEST DB ONLY)")
    print(f" Database : {db}")
    print(f" Tables   : {', '.join(TABLES)}")
    print("============================================================")

    auto = os.getenv("NO_CONFIRM") == "1"
    if auto:
        print("⚙️  NO_CONFIRM=1 set (skipping interactive confirmation).")
        confirm = CONFIRM_TOKEN
    else:
        confirm = input(f"Type '{CONFIRM_TOKEN}' to irreversibly CLEAR these tables: ").strip().lower()

    if confirm != CONFIRM_TOKEN:
        print("❌ Confirmation failed. Aborting.")
        sys.exit(3)

    try:
        async with get_session() as session:
            pre = await _get_counts(session)
            print("📊 Current row counts:")
            for t in TABLES:
                print(f"   {t}: {pre[t]}")

            for t in TABLES:
                print(f"🧹 TRUNCATE {t}")
                # NOWAIT helps reveal blocking locks quickly; remove NOWAIT if you prefer waiting.
                await session.execute(text(f'TRUNCATE "{t}" RESTART IDENTITY CASCADE'))

            await session.commit()

        async with get_session() as session:
            post = await _get_counts(session)

        print("✅ Truncate complete. Post-row counts:")
        for t in TABLES:
            print(f"   {t}: {post[t]}")
        print("✅ Done.")
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(4)


if __name__ == "__main__":
    asyncio.run(reset_active_baseline())