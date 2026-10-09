"""Administrative oversight is separate from request ownership and financial authority."""

from app.access.principal import Principal

SYSTEM_ADMIN_PERMISSIONS = frozenset(
    {"staff:manage", "organisation:manage", "office_assignment:manage"}
)


def is_system_administrator(actor: Principal) -> bool:
    return (
        actor.account.active
        and not actor.account.password_pending
        and not actor.account.read_only
        and SYSTEM_ADMIN_PERMISSIONS.issubset(actor.account.permissions)
    )
