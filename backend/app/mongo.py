"""MongoDB handles. MongoDB holds document *metadata* (AI results, encrypted OCR text, search tokens,
embeddings, officer feedback) and the encrypted file blobs (GridFS). PostgreSQL holds the structured
case data and the audit log."""
from __future__ import annotations

import gridfs
from pymongo import ASCENDING, MongoClient


class Mongo:
    def __init__(self, url: str, db_name: str):
        self.client = MongoClient(url, tz_aware=True, serverSelectionTimeoutMS=8000)
        self.db = self.client[db_name]
        self.doc_meta = self.db["doc_meta"]
        self.feedback = self.db["ai_feedback"]
        self.blobs = gridfs.GridFSBucket(self.db, bucket_name="blobs")

    def ensure_indexes(self) -> None:
        self.doc_meta.create_index([("document_id", ASCENDING), ("version_no", ASCENDING)], unique=True)
        self.doc_meta.create_index([("case_number", ASCENDING), ("current", ASCENDING)])
        self.doc_meta.create_index("kw")  # multikey: blind-index search tokens
        self.feedback.create_index([("created_at", ASCENDING)])

    def ping(self) -> None:
        self.client.admin.command("ping")

    def drop_database(self) -> None:  # tests
        self.client.drop_database(self.db.name)

    def close(self) -> None:
        self.client.close()
