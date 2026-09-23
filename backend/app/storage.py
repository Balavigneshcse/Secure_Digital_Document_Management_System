"""Object storage for encrypted blobs, in MongoDB GridFS. Only ciphertext is ever written here; the
interface (put/get/exists/delete by opaque key) is what an S3/MinIO adapter would also need."""
from __future__ import annotations

import re

import gridfs
from gridfs.errors import NoFile

_KEY_RE = re.compile(r"^[0-9a-f]{32}$")


class GridFSStorage:
    def __init__(self, bucket: gridfs.GridFSBucket):
        self.bucket = bucket

    @staticmethod
    def _check(key: str) -> str:
        if not _KEY_RE.match(key):
            raise ValueError("invalid storage key")
        return key

    def put(self, key: str, data: bytes) -> None:
        self._check(key)
        self.delete(key)  # keys are unique per version; replacing is only used by tests / repair
        self.bucket.upload_from_stream(key, data)

    def get(self, key: str) -> bytes:
        self._check(key)
        try:
            return self.bucket.open_download_stream_by_name(key).read()
        except NoFile as exc:
            raise FileNotFoundError(key) from exc

    def exists(self, key: str) -> bool:
        self._check(key)
        return next(self.bucket.find({"filename": key}, limit=1), None) is not None

    def delete(self, key: str) -> None:
        self._check(key)
        for f in self.bucket.find({"filename": key}):
            self.bucket.delete(f._id)
