from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, model_validator


class DateFilters(BaseModel):
    date_from: date | None = Field(default=None, ge=date(2, 1, 1))
    date_to: date | None = Field(default=None, ge=date(2, 1, 1), le=date(9999, 12, 30))

    @model_validator(mode="after")
    def ordered_dates(self) -> "DateFilters":
        if self.date_from and self.date_to and self.date_to < self.date_from:
            raise ValueError("End date must not precede start date")
        return self

    def bounds(self) -> tuple[datetime | None, datetime | None]:
        zone = ZoneInfo("Africa/Lagos")
        return (
            datetime.combine(self.date_from, time.min, zone).astimezone(UTC)
            if self.date_from
            else None,
            datetime.combine(self.date_to + timedelta(days=1), time.min, zone).astimezone(UTC)
            if self.date_to
            else None,
        )


class RequestFilters(DateFilters):
    search: str = Field(default="", max_length=250)
    requester: str = Field(default="", max_length=180)
    department: str = Field(default="", max_length=180)
    company: str = Field(default="", max_length=250)
    vendor: str = Field(default="", max_length=250)
    state: str = Field(default="", max_length=40)
    my_requests: bool = False
    inbox: bool = False
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class AuditFilters(DateFilters):
    search: str = Field(default="", max_length=250)
    action: str = Field(default="", max_length=100)
    actor: str = Field(default="", max_length=180)
    company: str = Field(default="", max_length=250)
    outcome: str = Field(default="", max_length=30)
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    before: datetime | None = None

    @model_validator(mode="after")
    def zoned(self) -> "AuditFilters":
        if self.before and self.before.tzinfo is None:
            raise ValueError("Snapshot time requires a timezone")
        return self
