from typing import Protocol
from uuid import UUID

from app.identity.models import Account


class Principal(Protocol):
    account: Account

    @property
    def id(self) -> UUID: ...
