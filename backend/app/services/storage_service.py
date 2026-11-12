import logging
import os
import re
from typing import Dict, Optional
from urllib.parse import quote

import httpx

from app.core.config import settings

logger = logging.getLogger("team_obsidian.storage")

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _safe_key_filename(sha_prefix: str, filename: str) -> str:
    stem, ext = os.path.splitext(filename or "document")
    clean_stem = re.sub(r"[^A-Za-z0-9_-]+", "_", stem).strip("_") or "document"
    clean_ext = re.sub(r"[^A-Za-z0-9]+", "", ext.lstrip("."))[:16]
    suffix = f".{clean_ext}" if clean_ext else ""
    return f"{sha_prefix}_{clean_stem[:64]}{suffix}"


class StorageService:
    """Durable binary storage backed by Supabase Object Storage with safe local disk cache/fallback."""

    def __init__(self) -> None:
        self._bucket_verified: Dict[str, bool] = {}

    def is_supabase_storage_configured(self) -> bool:
        return bool(
            (settings.SUPABASE_URL or "").strip()
            and (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
        )

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        key = settings.SUPABASE_SERVICE_ROLE_KEY.strip()
        headers = {
            "Authorization": f"Bearer {key}",
            "apikey": key,
        }
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _base_storage_url(self) -> str:
        return f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1"

    def ensure_bucket(self, bucket: Optional[str] = None) -> bool:
        bucket_name = bucket or settings.SUPABASE_STORAGE_BUCKET
        if not self.is_supabase_storage_configured():
            return False
        if self._bucket_verified.get(bucket_name):
            return True

        base = self._base_storage_url()
        try:
            with httpx.Client(timeout=15.0) as client:
                check = client.get(f"{base}/bucket/{quote(bucket_name, safe='')}", headers=self._headers())
                if check.status_code == 200:
                    self._bucket_verified[bucket_name] = True
                    return True
                create = client.post(
                    f"{base}/bucket",
                    headers=self._headers("application/json"),
                    json={
                        "id": bucket_name,
                        "name": bucket_name,
                        "public": False,
                        "file_size_limit": settings.MAX_UPLOAD_BYTES,
                    },
                )
                if create.status_code in (200, 201, 409):
                    self._bucket_verified[bucket_name] = True
                    return True
                logger.warning("Supabase bucket check/create returned %s: %s", create.status_code, create.text[:200])
        except Exception as exc:
            logger.warning("Supabase bucket check failed: %s", exc)
        return False

    def save_document_bytes(
        self,
        project_id: str,
        sha256_hash: str,
        filename: str,
        file_bytes: bytes,
        content_type: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Persist raw binary to Supabase Storage when configured and write local cache path."""
        safe_name = _safe_key_filename(sha256_hash[:16], filename)
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        local_path = os.path.join(UPLOAD_DIR, safe_name)[:500]
        try:
            with open(local_path, "wb") as fh:
                fh.write(file_bytes)
        except Exception as exc:
            logger.warning("Local cache write skipped for %s: %s", safe_name, exc)
            local_path = None

        bucket_name = settings.SUPABASE_STORAGE_BUCKET
        storage_key = f"{project_id}/{safe_name}"
        if self.is_supabase_storage_configured() and self.ensure_bucket(bucket_name):
            encoded_key = quote(storage_key, safe="/")
            url = f"{self._base_storage_url()}/object/{quote(bucket_name, safe='')}/{encoded_key}"
            headers = self._headers(content_type or "application/octet-stream")
            headers["x-upsert"] = "true"
            try:
                with httpx.Client(timeout=30.0) as client:
                    res = client.post(url, headers=headers, content=file_bytes)
                if 200 <= res.status_code < 300:
                    return {
                        "storage_bucket": bucket_name,
                        "storage_key": storage_key,
                        "storage_path": local_path,
                        "backend": "supabase",
                    }
                logger.warning("Supabase Storage upload returned %s: %s", res.status_code, res.text[:200])
            except Exception as exc:
                logger.warning("Supabase Storage upload failed, falling back to local storage: %s", exc)

        return {
            "storage_bucket": None,
            "storage_key": None,
            "storage_path": local_path,
            "backend": "local",
        }

    def read_document_bytes(
        self,
        storage_bucket: Optional[str],
        storage_key: Optional[str],
        storage_path: Optional[str],
    ) -> Optional[bytes]:
        """Read raw binary from durable Supabase Storage first (or local cache if present)."""
        if storage_path and os.path.exists(storage_path):
            try:
                with open(storage_path, "rb") as fh:
                    return fh.read()
            except Exception as exc:
                logger.warning("Local read failed for %s: %s", storage_path, exc)

        if storage_bucket and storage_key and self.is_supabase_storage_configured():
            encoded_key = quote(storage_key, safe="/")
            url = f"{self._base_storage_url()}/object/{quote(storage_bucket, safe='')}/{encoded_key}"
            try:
                with httpx.Client(timeout=30.0) as client:
                    res = client.get(url, headers=self._headers())
                if res.status_code == 200:
                    return res.content
                logger.warning("Supabase Storage download returned %s for %s", res.status_code, storage_key)
            except Exception as exc:
                logger.warning("Supabase Storage download failed for %s: %s", storage_key, exc)

        return None

    def delete_document_bytes(
        self,
        storage_bucket: Optional[str],
        storage_key: Optional[str],
        storage_path: Optional[str],
    ) -> None:
        if storage_path and os.path.exists(storage_path):
            try:
                os.remove(storage_path)
            except Exception:
                pass
        if storage_bucket and storage_key and self.is_supabase_storage_configured():
            encoded_key = quote(storage_key, safe="/")
            url = f"{self._base_storage_url()}/object/{quote(storage_bucket, safe='')}/{encoded_key}"
            try:
                with httpx.Client(timeout=15.0) as client:
                    client.delete(url, headers=self._headers())
            except Exception as exc:
                logger.warning("Supabase Storage delete failed for %s: %s", storage_key, exc)


storage_service = StorageService()

