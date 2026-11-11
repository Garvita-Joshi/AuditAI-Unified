from decimal import Decimal
from backend.app.sourcing.requirements import Requirements
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator

Money = Annotated[Decimal, Field(ge=0, max_digits=15, decimal_places=2, allow_inf_nan=False)]


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: str = Field(min_length=1, max_length=100, pattern=r"^\S(?:.*\S)?$")
    description: str = Field(min_length=1, max_length=500)
    quantity: int = Field(gt=0, le=100000)
    unit_price: Money


class PurchaseTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")
    supplier_id: str = Field(min_length=1, max_length=100)
    recipient_id: str = Field(min_length=1, max_length=200)
    currency: Literal["USD", "INR"] = "USD"
    items: list[LineItem] = Field(min_length=1, max_length=100)
    delivery: Money = Decimal("0.00")
    tax: Money = Decimal("0.00")

    @field_validator("supplier_id", "recipient_id", mode="before")
    @classmethod
    def trim_identifiers(cls, value):
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def unique_skus(self):
        skus = [item.sku for item in self.items]
        if len(skus) != len(set(skus)):
            raise ValueError("Each SKU must occur once; merge duplicate line items.")
        if self.total > Decimal("9999999999999.99"):
            raise ValueError("Order total exceeds supported monetary range.")
        return self

    @property
    def total(self) -> Decimal:
        return sum((item.quantity * item.unit_price for item in self.items), Decimal("0.00")) + self.delivery + self.tax


class RequestDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")
    department: str = Field(default="Operations", min_length=1, max_length=100)
    category: str = Field(default="Office equipment", min_length=1, max_length=100)
    purpose: str = Field(default="", max_length=2000)
    sourcing_requirements: Requirements | None = None
    shares_personal_data: bool | None = False
    data_types: list[Literal[
        "Confidential Business Information",
        "Company Financial Data",
        "Marketing Data",
        "Personal Data (e.g. name, email, location, etc.)",
    ]] = Field(default_factory=list, max_length=4)
    data_usage: str = Field(default="", max_length=2000)
    payment_terms: Literal["Due on receipt", "Net 15", "Net 30", "Net 60"] = "Due on receipt"

    @model_validator(mode="after")
    def describe_data_usage(self):
        if self.shares_personal_data is True:
            if not self.data_types:
                raise ValueError("Select at least one type of information shared with the supplier.")
            if not self.data_usage.strip():
                raise ValueError("Describe how the supplier will use the shared information.")
        return self


class RequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    budget_limit: Money
    details: RequestDetails = Field(default_factory=RequestDetails)
    terms: PurchaseTerms

    @model_validator(mode="after")
    def within_budget(self):
        if self.terms.total <= 0:
            raise ValueError("Purchase total must be positive.")
        if self.terms.total > self.budget_limit:
            raise ValueError("Request exceeds its spending limit.")
        return self


class InvoiceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invoice_number: str = Field(min_length=1, max_length=100)
    terms: PurchaseTerms
    stated_total: Money

    @field_validator("invoice_number", mode="before")
    @classmethod
    def canonical_invoice_number(cls, value):
        return value.strip().upper() if isinstance(value, str) else value


def match_invoice(approved: PurchaseTerms, invoice: InvoiceCreate) -> list[dict]:
    """Exact SKU matching for the MVP. Missing evidence never becomes a pass."""
    differences = []

    def compare(field, expected, actual):
        if expected != actual:
            differences.append({"field": field, "expected": str(expected), "actual": str(actual)})

    for field in ("supplier_id", "recipient_id", "currency", "delivery", "tax"):
        compare(field, getattr(approved, field), getattr(invoice.terms, field))
    expected = {item.sku: item for item in approved.items}
    actual = {item.sku: item for item in invoice.terms.items}
    for sku in sorted(expected.keys() | actual.keys()):
        if sku not in expected:
            differences.append({"field": f"items.{sku}", "expected": "absent", "actual": "unexpected item"})
        elif sku not in actual:
            differences.append({"field": f"items.{sku}", "expected": "required item", "actual": "missing"})
        else:
            for field in ("quantity", "unit_price", "description"):
                compare(f"items.{sku}.{field}", getattr(expected[sku], field), getattr(actual[sku], field))
    compare("invoice_arithmetic", invoice.terms.total, invoice.stated_total)
    compare("approved_total", approved.total, invoice.stated_total)
    return differences
