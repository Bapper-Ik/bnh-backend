"""Authenticated Cloudinary raw assets, proxied through authorised application reads."""

import hashlib
import time
from typing import Protocol

import httpx
from cloudinary.utils import api_sign_request, private_download_url  # type: ignore[import-untyped]

from app.core.config import Settings
from app.core.errors import DomainError


class Storage(Protocol):
    async def put(self, key: str, data: bytes, media_type: str) -> str: ...
    async def get(self, key: str, digest: str, size: int) -> bytes: ...


def unavailable() -> DomainError:
    return DomainError(
        "SERVICE_UNAVAILABLE", "Private document storage is unavailable. Try again later.", 503
    )


class CloudinaryStorage:
    def __init__(self, settings: Settings):
        self.settings = settings

    def credentials(self) -> dict[str, str]:
        cfg = self.settings
        if not (cfg.cloudinary_cloud_name and cfg.cloudinary_api_key and cfg.cloudinary_api_secret):
            raise unavailable()
        return {
            "cloud_name": cfg.cloudinary_cloud_name,
            "api_key": cfg.cloudinary_api_key.get_secret_value(),
            "api_secret": cfg.cloudinary_api_secret.get_secret_value(),
        }

    async def put(self, key: str, data: bytes, media_type: str) -> str:
        cfg = self.credentials()
        params = {
            "timestamp": str(int(time.time())),
            "public_id": key,
            "type": "authenticated",
            "overwrite": "false",
        }
        signature = api_sign_request(params, cfg["api_secret"], algorithm="sha256")
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
                response = await client.post(
                    f"https://api.cloudinary.com/v1_1/{cfg['cloud_name']}/raw/upload",
                    data={**params, "api_key": cfg["api_key"], "signature": signature},
                    files={"file": ("document", data, media_type)},
                )
                if response.status_code != 200:
                    raise unavailable()
                result = response.json()
                if (
                    result.get("public_id") != key
                    or result.get("type") != "authenticated"
                    or result.get("resource_type") != "raw"
                    or result.get("bytes") != len(data)
                    or not result.get("version")
                ):
                    raise unavailable()
                return str(result["version"])
        except (httpx.HTTPError, ValueError) as exc:
            raise unavailable() from exc

    async def get(self, key: str, digest: str, size: int) -> bytes:
        url = private_download_url(
            key,
            None,
            resource_type="raw",
            type="authenticated",
            expires_at=int(time.time()) + 60,
            attachment=True,
            **self.credentials(),
        )
        try:
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
                async with client.stream("GET", url) as response:
                    if response.status_code != 200:
                        raise unavailable()
                    data = bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(data) + len(chunk) > size:
                            raise unavailable()
                        data.extend(chunk)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise unavailable()
            return bytes(data)
        except httpx.HTTPError as exc:
            raise unavailable() from exc
