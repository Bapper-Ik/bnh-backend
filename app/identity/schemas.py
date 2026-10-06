from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Command):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


class Reauthenticate(Command):
    password: str = Field(min_length=1, max_length=1024)


class UserView(BaseModel):
    id: UUID
    account_id: UUID
    name: str
    email: str
    permissions: list[str]
    read_only: bool = False


class Message(BaseModel):
    message: str


class Recover(Command):
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


class AccountCreate(Command):
    name: str = Field(min_length=2, max_length=180)
    email: EmailStr
    initial_password: str = Field(min_length=12, max_length=1024)
