"""Demo helper: flips one bit inside the stored, encrypted copy of a document - what an attacker with database access
could do. The next Verify / Download must then report TAMPERED and the audit log must record a TAMPER_DETECTED alert.

    Get-Content deploy\\tamper_demo.py | docker compose exec -T backend python - 1 1   # PowerShell; document 1, version 1
    docker compose exec -T backend python - 1 1 < deploy/tamper_demo.py               # bash / cmd
    cd backend; .venv\\Scripts\\python ..\\deploy\\tamper_demo.py 1 1                    # native run (reads backend/.env)

Only for demonstrations on data you can afford to lose: the change is irreversible.
"""
from __future__ import annotations

import pathlib
import sys

# Makes `app` importable regardless of cwd/invocation (a plain `python deploy/tamper_demo.py` run from the
# project root has no way to see `backend/app` otherwise - piping the script over stdin sidesteps this by
# using the caller's cwd as sys.path[0], which is why that form worked without this).
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from pymongo import MongoClient
from sqlalchemy import create_engine, text

from app.config import Settings

if len(sys.argv) != 3:
    sys.exit("usage: tamper_demo.py <document_id> <version_no>")
doc_id, version = int(sys.argv[1]), int(sys.argv[2])

s = Settings()
with create_engine(s.database_url).connect() as conn:
    key = conn.execute(
        text("select storage_key from document_versions where document_id = :d and version_no = :v"),
        {"d": doc_id, "v": version},
    ).scalar_one_or_none()
if key is None:
    sys.exit(f"no version {version} of document {doc_id}")

db = MongoClient(s.mongo_url)[s.mongo_db]
blob = db["blobs.files"].find_one({"filename": key})
chunk = db["blobs.chunks"].find_one({"files_id": blob["_id"], "n": 0}) if blob else None
if chunk is None:
    sys.exit("stored blob not found")
data = bytearray(chunk["data"])
data[len(data) // 2] ^= 0x01
db["blobs.chunks"].update_one({"_id": chunk["_id"]}, {"$set": {"data": bytes(data)}})
print(f"flipped 1 bit of the stored ciphertext of document {doc_id} v{version} ({len(data)} bytes in chunk 0). Now click Verify.")
