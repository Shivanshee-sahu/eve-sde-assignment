from datetime import datetime
from decimal import Decimal
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int
    pages: int


class Signup(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    model_config = ConfigDict(extra="forbid")


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    model_config = ConfigDict(from_attributes=True)


class Login(BaseModel):
    email: EmailStr
    password: str
    model_config = ConfigDict(extra="forbid")


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TestOut(BaseModel):
    id: int
    name: str
    description: str
    price: Decimal


class CentreOut(BaseModel):
    id: int
    name: str
    location: str
    tests: list[TestOut]


class CentreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=1, max_length=255)
    model_config = ConfigDict(extra="forbid")


class TestCatalogOut(BaseModel):
    id: int
    name: str
    description: str
    model_config = ConfigDict(from_attributes=True)


class DiagnosticTestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=500)
    model_config = ConfigDict(extra="forbid")


class CentreTestCreate(BaseModel):
    test_id: int = Field(gt=0)
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    model_config = ConfigDict(extra="forbid")


class BookingCreate(BaseModel):
    centre_id: int
    test_id: int
    appointment_datetime: datetime
    model_config = ConfigDict(extra="forbid")


class BookingOut(BaseModel):
    id: int
    user_id: int
    centre_id: int
    test_id: int
    appointment_datetime: datetime
    amount: Decimal
    status: str
    model_config = ConfigDict(from_attributes=True)


class PaymentCreate(BaseModel):
    booking_id: int
    model_config = ConfigDict(extra="forbid")


class PaymentOut(BaseModel):
    payment_id: int
    booking_id: int
    amount: Decimal
    status: str
    provider_payment_id: str


class WebhookIn(BaseModel):
    event_id: str = Field(min_length=1, max_length=120)
    event_type: str = Field(min_length=1, max_length=80)
    payment_id: str = Field(min_length=1, max_length=80)
    status: str
    model_config = ConfigDict(extra="forbid")


class WebhookOut(BaseModel):
    received: bool = True
    duplicate: bool = False
    processing_status: str = "RECEIVED"
