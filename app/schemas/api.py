from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class UserOut(ORMModel):
    id: int
    name: str
    created_at: datetime


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class GroupOut(ORMModel):
    id: int
    name: str
    created_at: datetime


class MemberCreate(BaseModel):
    user_id: int = Field(gt=0)


class MemberOut(BaseModel):
    id: int
    name: str
    joined_at: datetime


class ExpenseCreate(BaseModel):
    paid_by: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    description: str = Field(min_length=1, max_length=240)
    category: str | None = Field(default=None, max_length=80)
    @field_validator("description")
    @classmethod
    def strip_description(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("description cannot be blank")
        return value


class SplitOut(BaseModel):
    user_id: int
    user_name: str
    owed_amount: Decimal


class ExpenseOut(BaseModel):
    id: int
    group_id: int
    paid_by: int
    payer_name: str
    amount: Decimal
    description: str
    category: str | None
    created_at: datetime
    splits: list[SplitOut]


class ExpensePage(BaseModel):
    items: list[ExpenseOut]
    limit: int
    offset: int


class SettlementCreate(BaseModel):
    paid_by: int = Field(gt=0)
    paid_to: int = Field(gt=0)
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)


class SettlementOut(BaseModel):
    id: int
    group_id: int
    paid_by: int
    paid_to: int
    amount: Decimal
    created_at: datetime


class DebtOut(BaseModel):
    debtor_id: int
    debtor_name: str
    creditor_id: int
    creditor_name: str
    amount: Decimal


class BalanceMemberOut(BaseModel):
    user_id: int
    name: str
    net_balance: Decimal


class BalancesOut(BaseModel):
    group_id: int
    members: list[BalanceMemberOut]
    debts: list[DebtOut]


class SuggestionOut(BaseModel):
    paid_by: int
    payer_name: str
    paid_to: int
    receiver_name: str
    amount: Decimal


class SuggestionsOut(BaseModel):
    group_id: int
    suggestions: list[SuggestionOut]
