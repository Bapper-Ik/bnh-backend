"""Administrator-selected department abbreviations for new requisition references."""

from typing import Annotated

from pydantic import AfterValidator, Field

DepartmentCode = Annotated[
    str,
    Field(min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$"),
    AfterValidator(str.upper),
]
