"""Fixed capabilities; financial powers come only from current scoped appointments."""

ADMIN_PERMISSIONS = frozenset(
    {"staff:manage", "organisation:manage", "office_assignment:manage", "audit:read"}
)
STAFF_PERMISSIONS = frozenset(
    {
        "requisition:create",
        "requisition:list",
        "requisition:read",
        "requisition:update",
        "requisition:submit",
        "attachment:upload",
        "attachment:read",
        "signature:capture",
        "requisition:export",
    }
)
DECISION_PERMISSIONS = frozenset(
    {"requisition:approve", "requisition:reject", "requisition:return"}
)
BOARD_PERMISSIONS = frozenset(
    {"board_resolution:record", "board_resolution:confirm", "board_resolution:return"}
)
PERMISSION_REGISTRY = (
    ADMIN_PERMISSIONS | STAFF_PERMISSIONS | DECISION_PERMISSIONS | BOARD_PERMISSIONS
)
READ_PERMISSIONS = frozenset(
    {"requisition:list", "requisition:read", "attachment:read", "requisition:export", "audit:read"}
)
