import os, sys, asyncio

personal_access_token = os.environ.get("REVERB_API_KEY")

sys.path.append(os.path.abspath("/Users/wommy/Documents/GitHub/PROJECTS/HANKS/inventory_system"))
from app.services.reverb.client import ReverbClient


if __name__ == "__main__":
    reverb_client = ReverbClient(personal_access_token)
    acounts = asyncio.run(reverb_client.get_my_counts())




