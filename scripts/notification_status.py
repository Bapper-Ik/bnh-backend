"""Print aggregate delivery diagnostics without recipients or message contents."""

import asyncio
import json

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.models import OutboxItem
from app.core.config import get_settings
from app.core.database import make_engine
from app.notifications.models import Notification


async def snapshot(s: AsyncSession) -> dict[str, list[dict[str, object]]]:
    alerts = await s.execute(
        select(
            Notification.email_status,
            Notification.last_error,
            func.count(),
            func.max(Notification.attempts),
            func.min(Notification.available_at),
        ).group_by(Notification.email_status, Notification.last_error)
    )
    intents = await s.execute(
        select(OutboxItem.status, func.count(), func.max(OutboxItem.attempts))
        .where(OutboxItem.destination == "requisition_notification")
        .group_by(OutboxItem.status)
    )
    return {
        "email": [
            {
                "status": state,
                "reason": reason,
                "count": count,
                "max_attempts": attempts,
                "earliest_available_at": available.isoformat() if available else None,
            }
            for state, reason, count, attempts, available in alerts
        ],
        "in_app_projection": [
            {"status": state, "count": count, "max_attempts": attempts}
            for state, count, attempts in intents
        ],
    }


async def main() -> None:
    engine = make_engine(get_settings())
    try:
        async with async_sessionmaker(engine)() as session:
            print(json.dumps(await snapshot(session), indent=2))
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        raise SystemExit(
            "Notification diagnostics unavailable; check database configuration."
        ) from None
