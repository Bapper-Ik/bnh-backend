import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr

from app.notifications.delivery import DeliveryFailure, send_resend
from app.notifications.models import Notification


@pytest.mark.parametrize(
    "status,body,code,retryable",
    [
        (200, {"id": "bad"}, "provider_invalid_response", True),
        (429, {}, "provider_rate_limit", True),
        (503, {"message": "private response"}, "provider_temporary_failure", True),
        (422, {"message": "private response"}, "provider_rejected", False),
        (409, {"name": "invalid_idempotent_request"}, "provider_idempotency_conflict", False),
        (409, {"name": "concurrent_idempotent_requests"}, "provider_temporary_failure", True),
    ],
)
async def test_provider_errors_are_safe_and_classified(
    settings, monkeypatch, status, body, code, retryable
):
    async def post(self, url, **kwargs):
        return httpx.Response(status, json=body, headers={"retry-after": "120"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = settings.model_copy(update={"resend_api_key": SecretStr("test-secret")})
    row = Notification(
        id=uuid4(),
        requisition_id=uuid4(),
        template="approval_required",
        template_version="v1",
        kind="approval_task",
        sender_address="sender@example.com",
        recipient_address="recipient@example.com",
        link_origin="https://app.example.com",
        available_at=datetime.now(UTC),
    )
    with pytest.raises(DeliveryFailure) as caught:
        await send_resend(config, row, "BNH-SYNTHETIC")
    assert caught.value.code == code and caught.value.retryable == retryable
    assert "private" not in str(caught.value)
    if status == 429:
        assert caught.value.retry_after == 120


async def test_email_identical_retries_minimal_payload_and_authenticated_link(
    settings, monkeypatch
):
    sent = []
    provider_id = uuid4()

    async def post(self, url, **kwargs):
        assert url == "https://api.resend.com/emails"
        sent.append(kwargs)
        return httpx.Response(200, json={"id": str(provider_id)})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    config = settings.model_copy(update={"resend_api_key": SecretStr("test-secret")})
    row = Notification(
        id=uuid4(),
        requisition_id=uuid4(),
        template="board_review_required",
        template_version="v1",
        kind="board_signoff_task",
        sender_address="sender@example.com",
        recipient_address="recipient@example.com",
        link_origin="https://app.example.com",
        available_at=datetime.now(UTC),
    )
    for _ in range(2):
        assert await send_resend(config, row, "BNH-SYNTHETIC") == provider_id
    assert sent[0] == sent[1]
    assert sent[0]["headers"]["Idempotency-Key"] == f"custodian-notification/{row.id}/v1"
    payload = sent[0]["json"]
    assert set(payload) == {"from", "to", "subject", "text"}
    assert f"https://app.example.com/requisitions/{row.requisition_id}/board" in payload["text"]
    assert "This link cannot approve" in payload["text"]
    assert not any(
        secret in json.dumps(payload)
        for secret in ["test-secret", "strokes", "account_number", "attachments", "token="]
    )
