"""Encrypted file storage for report PDFs.

PDFs are encrypted with Fernet (AES-128-CBC + HMAC) before touching disk, so a copied disk
or backup does not expose patient reports. Swap LocalEncryptedStorage for an S3-compatible
store (e.g. MinIO on a Bangladeshi cloud) later; keep the same two methods.
"""
import hashlib
import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from .config import get_settings


class LocalEncryptedStorage:
    def __init__(self, root: str, key: str):
        if not key:
            raise RuntimeError(
                "FILE_ENCRYPTION_KEY is not set. Generate one with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.fernet = Fernet(key.encode())

    def save(self, data: bytes) -> tuple[str, str]:
        """Encrypt and store; returns (file_key, sha256 of the original)."""
        file_key = secrets.token_hex(16)
        self.root.mkdir(parents=True, exist_ok=True)  # in case the folder was removed while running
        (self.root / f"{file_key}.bin").write_bytes(self.fernet.encrypt(data))
        return file_key, hashlib.sha256(data).hexdigest()

    def load(self, file_key: str) -> bytes:
        if not file_key.isalnum():
            raise ValueError("bad file key")
        return self.fernet.decrypt((self.root / f"{file_key}.bin").read_bytes())


_storage: LocalEncryptedStorage | None = None


def get_storage() -> LocalEncryptedStorage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = LocalEncryptedStorage(s.storage_dir, s.file_encryption_key or os.environ.get("FILE_ENCRYPTION_KEY", ""))
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
