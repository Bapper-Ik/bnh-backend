import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from enum import IntEnum
from typing import Literal

POLICY_VERSION = "bnh-doa-v1"
MAX_TOTAL = Decimal("999999999999999.99")


class Authority(IntEnum):
    HOD = 1
    CHIEF_OF_STAFF = 2
    MD = 3
    BOARD = 4

    @property
    def label(self) -> str:
        return {
            self.HOD: "hod",
            self.CHIEF_OF_STAFF: "chief_of_staff",
            self.MD: "md",
            self.BOARD: "board",
        }[self]


def exact_decimal(value: str, places: int, *, positive: bool = False) -> Decimal:
    if (
        not isinstance(value, str)
        or len(value) > 40
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value)
    ):
        raise ValueError("Supply a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        raise ValueError("Invalid nonnegative/positive value")
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or exponent < -places or number > MAX_TOTAL:
        raise ValueError(f"Value exceeds supported precision (at most {places} decimal places)")
    return number


def calculate_lines(items: list[tuple[str, str]]) -> tuple[list[str], str]:
    totals = []
    with localcontext() as ctx:
        ctx.prec = 50
        for quantity, price in items:
            qty = exact_decimal(quantity, 4, positive=True)
            rate = exact_decimal(price, 2)
            total = (qty * rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if total > MAX_TOTAL:
                raise ValueError("Line total exceeds supported precision")
            totals.append(total)
        grand = sum(totals, Decimal("0.00"))
    if grand > MAX_TOTAL:
        raise ValueError("Total exceeds supported precision")
    return [format(x, ".2f") for x in totals], format(grand, ".2f")


@dataclass(frozen=True)
class Route:
    authority: Authority
    amount_authority: Authority
    requester_floor: Authority
    explanation: str
    policy_version: str = POLICY_VERSION


def resolve(total: str, offices: set[str], currency: Literal["NGN"] = "NGN") -> Route:
    amount = exact_decimal(total, 2, positive=True)
    if currency != "NGN" or amount < 1:
        raise ValueError("Submission requires NGN and at least one naira")
    band = (
        Authority.HOD
        if amount <= Decimal("5000000")
        else Authority.CHIEF_OF_STAFF
        if amount <= Decimal("100000000")
        else Authority.MD
        if amount <= Decimal("500000000")
        else Authority.BOARD
    )
    floor = (
        Authority.BOARD
        if "md" in offices
        else Authority.MD
        if "chief_of_staff" in offices
        else Authority.CHIEF_OF_STAFF
        if "hod" in offices
        else Authority.HOD
    )
    authority = max(band, floor)
    explanation = f"Amount requires {band.label.replace('_', ' ')}."
    if floor > band:
        explanation += (
            f" Requester's office raises required authority to {floor.label.replace('_', ' ')}."
        )
    return Route(
        authority=authority, amount_authority=band, requester_floor=floor, explanation=explanation
    )
