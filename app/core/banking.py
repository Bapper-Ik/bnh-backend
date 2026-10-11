import re


def validate_account_number(value: str) -> None:
    """Validate new account capture without coercing away leading zeroes."""
    if not re.fullmatch(r"[0-9]{10}", value):
        raise ValueError("Account number must contain exactly 10 digits")
