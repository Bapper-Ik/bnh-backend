"""Exact NGN words, including kobo, without binary floating-point conversion."""

from decimal import Decimal

SMALL = (
    "Zero One Two Three Four Five Six Seven Eight Nine Ten Eleven Twelve Thirteen "
    "Fourteen Fifteen Sixteen Seventeen Eighteen Nineteen"
).split()
TENS = "Zero Ten Twenty Thirty Forty Fifty Sixty Seventy Eighty Ninety".split()


def integer_words(number: int) -> str:
    if number < 20:
        return SMALL[number]
    if number < 100:
        tens, units = divmod(number, 10)
        return TENS[tens] + ("-" + SMALL[units] if units else "")
    if number < 1000:
        hundreds, remainder = divmod(number, 100)
        return (
            SMALL[hundreds] + " Hundred" + (" and " + integer_words(remainder) if remainder else "")
        )
    for size, label in [
        (10**12, "Trillion"),
        (10**9, "Billion"),
        (10**6, "Million"),
        (1000, "Thousand"),
    ]:
        if number >= size:
            major, remainder = divmod(number, size)
            return (
                integer_words(major)
                + " "
                + label
                + (
                    (" and " if remainder < 100 else " ") + integer_words(remainder)
                    if remainder
                    else ""
                )
            )
    raise ValueError("Invalid amount")


def naira_words(amount: str) -> str:
    value = Decimal(amount)
    if not value.is_finite() or value < 0 or value >= Decimal("1000000000000000"):
        raise ValueError("Amount is outside the supported NGN range")
    if value != value.quantize(Decimal("0.01")):
        raise ValueError("Amount must be exact to the kobo")
    naira, kobo = divmod(int(value * 100), 100)
    return (
        integer_words(naira)
        + " Naira"
        + (" and " + integer_words(kobo) + " Kobo" if kobo else "")
        + " Only"
    )
