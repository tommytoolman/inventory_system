# python scripts/backup_db.py
import subprocess, os, datetime, pathlib
from dotenv import load_dotenv
load_dotenv('.env')
url = os.getenv('DATABASE_URL')  # postgresql+asyncpg://inventory_user:pwd@localhost/inventory_test
parts = url.split("://",1)[1].split("@")
auth, hostdb = parts
user = auth.split(":")[0]
host, db = hostdb.split("/",1)
password = auth.split(":")[1].split("@")[0]
os.environ['PGPASSWORD'] = password
ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
out_dir = pathlib.Path("backups/db")
out_dir.mkdir(parents=True, exist_ok=True)
dump_file = out_dir / f"{db}_{ts}.dump"
subprocess.check_call([
    "pg_dump","-U",user,"-h",host,"-d",db,"-F","c","-f",str(dump_file)
])
print(f"Created {dump_file}")