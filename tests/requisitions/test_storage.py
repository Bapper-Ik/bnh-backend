import hashlib
import json
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import SecretStr

from app.core.errors import DomainError
from app.evidence.storage import CloudinaryStorage


async def test_authenticated_raw_cloudinary_upload_and_private_digest_checked_download(
    settings, monkeypatch
):
    cfg = settings.model_copy(
        update={
            "cloudinary_cloud_name": "synthetic",
            "cloudinary_api_key": SecretStr("synthetic-key"),
            "cloudinary_api_secret": SecretStr("synthetic-secret"),
        }
    )
    data = b"synthetic test content"
    key = "requisitions/synthetic/immutable"
    requests = []

    def transport(request):
        requests.append(request)
        assert request.url.host == "api.cloudinary.com"
        if request.method == "POST":
            assert request.url.path == "/v1_1/synthetic/raw/upload"
            body = request.content
            assert b"authenticated" in body and b"overwrite" in body and b"false" in body
            assert b"synthetic-secret" not in body
            return httpx.Response(
                200,
                json={
                    "public_id": key,
                    "resource_type": "raw",
                    "type": "authenticated",
                    "bytes": len(data),
                    "version": 123,
                },
            )
        query = parse_qs(request.url.query.decode())
        assert query["type"] == ["authenticated"] and query["public_id"] == [key]
        assert query["expires_at"] and query["signature"]
        assert "synthetic-secret" not in str(request.url)
        return httpx.Response(200, content=data)

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        "app.evidence.storage.httpx.AsyncClient",
        lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(transport)),
    )
    storage = CloudinaryStorage(cfg)
    assert await storage.put(key, data, "application/pdf") == "123"
    assert await storage.get(key, hashlib.sha256(data).hexdigest(), len(data)) == data
    with pytest.raises(DomainError):
        await storage.get(key, "0" * 64, len(data))
    with pytest.raises(DomainError):
        await storage.get(key, hashlib.sha256(data).hexdigest(), 1)
    assert len(requests) == 4


async def test_storage_does_not_accept_public_or_unavailable_uploads(settings, monkeypatch):
    cfg = settings.model_copy(
        update={
            "cloudinary_cloud_name": "synthetic",
            "cloudinary_api_key": SecretStr("key"),
            "cloudinary_api_secret": SecretStr("secret"),
        }
    )
    with pytest.raises(DomainError, match="unavailable"):
        await CloudinaryStorage(settings).put("test", b"test", "application/pdf")
    real_client = httpx.AsyncClient
    for response in [
        httpx.Response(503),
        httpx.Response(
            200,
            content=json.dumps(
                {
                    "public_id": "test",
                    "type": "upload",
                    "resource_type": "raw",
                    "bytes": 4,
                    "version": 1,
                }
            ),
        ),
    ]:
        monkeypatch.setattr(
            "app.evidence.storage.httpx.AsyncClient",
            lambda response=response, **kwargs: real_client(
                **kwargs, transport=httpx.MockTransport(lambda request: response)
            ),
        )
        with pytest.raises(DomainError):
            await CloudinaryStorage(cfg).put("test", b"test", "application/pdf")
