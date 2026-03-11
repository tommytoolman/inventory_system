import asyncio, pprint
from app.services.vintageandrare.client import VintageAndRareClient
from app.core.config import get_settings

async def main():
    s = get_settings()
    client = VintageAndRareClient(s.VINTAGE_AND_RARE_USERNAME, s.VINTAGE_AND_RARE_PASSWORD)
    # raw GET to base
    try:
        r = client.session.get(client.BASE_URL)
        print("GET base:", r.status_code, r.headers.get("Server"), r.text[:200])
    except Exception as exc:
        print("GET base failed:", exc)
    # attempt login (will try Selenium fallback if 403 and SELENIUM_GRID_URL is set)
    ok = await client.authenticate()
    print("Auth result:", ok)
    print("Cookies after auth:", client.session.cookies.get_dict())

asyncio.run(main())
