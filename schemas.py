from datetime import date, datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Product(BaseModel):
    model_config = ConfigDict(frozen=True)

    product_id: str
    name: str
    category: str
    description: str = ""
    attributes: dict[str, Any] = Field(default_factory=dict)
    listed_price_inr: int = Field(gt=0)
    stock: int = Field(ge=0)
    delivery_days: int = Field(ge=0)
    rating: float = Field(ge=0, le=5)
    review_count: int = Field(ge=0)


class SellerPolicy(BaseModel):
    minimum_price_inr: int = Field(gt=0)
    automatic_approval_floor_inr: int = Field(gt=0)
    seller_instructions: str = ""

    @model_validator(mode="after")
    def validate_price_policy(self) -> "SellerPolicy":
        if self.automatic_approval_floor_inr < self.minimum_price_inr:
            raise ValueError("Automatic approval floor cannot be below minimum price")
        return self


class SellerProfile(BaseModel):
    seller_id: str
    display_name: str
    products: list[Product]
    policies: dict[str, SellerPolicy]

    @model_validator(mode="after")
    def validate_policies(self) -> "SellerProfile":
        product_ids = {product.product_id for product in self.products}
        if set(self.policies) != product_ids:
            raise ValueError("Every product must have exactly one seller policy")
        for product in self.products:
            policy = self.policies[product.product_id]
            if policy.automatic_approval_floor_inr > product.listed_price_inr:
                raise ValueError("Automatic approval floor cannot exceed listed price")
            if policy.minimum_price_inr > product.listed_price_inr:
                raise ValueError("Minimum price cannot exceed listed price")
        return self


class BuyerRequest(BaseModel):
    product_category: str
    quantity: int = Field(gt=0)
    max_budget_inr: int = Field(gt=0)
    delivery_deadline_days: int | None = Field(default=None, ge=0)
    hard_constraints: dict[str, Any] = Field(default_factory=dict)
    preferences: list[str] = Field(default_factory=list)
    original_text: str = ""
    buyer_approval_limit_inr: int | None = Field(default=None, gt=0)


class DeliveryDestination(BaseModel):
    location: str
    quantity: int = Field(gt=0)
    deadline_days: int = Field(ge=0)


class ProcurementPlan(BaseModel):
    request: BuyerRequest
    total_quantity: int = Field(gt=0)
    total_budget_inr: int = Field(gt=0)
    destinations: list[DeliveryDestination] = Field(default_factory=list)
    allow_split_orders: bool = True


class SupplierRiskProfile(BaseModel):
    supplier_id: str
    reliability_score: float = Field(ge=0, le=1)
    risk_flags: list[str] = Field(default_factory=list)


class AgreementVersion(BaseModel):
    version: int = Field(ge=1)
    canonical_json: str
    sha256: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Offer(BaseModel):
    offer_id: str
    seller_id: str
    product_id: str
    quantity: int = Field(gt=0)
    unit_price_inr: int = Field(gt=0)
    total_price_inr: int = Field(gt=0)
    delivery_days: int = Field(ge=0)
    terms: dict[str, Any] = Field(default_factory=dict)
    round_number: int = Field(ge=1)
    status: Literal["proposed", "accepted", "rejected", "countered"] = "proposed"
    requires_seller_approval: bool = False
    seller_approval_status: Literal["not_required", "pending", "approved", "rejected"] = "not_required"
    expires_at: datetime | None = None
    supplier_risk_score: float = Field(default=0.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_total(self) -> "Offer":
        if self.total_price_inr != self.quantity * self.unit_price_inr:
            raise ValueError("Offer total must equal quantity multiplied by unit price")
        return self


class NegotiationMessage(BaseModel):
    sender_id: str
    sender_role: Literal["buyer_agent", "seller_agent", "seller_human", "system"]
    message: str
    round_number: int = Field(ge=1)
    message_type: Literal[
        "request", "offer", "counteroffer", "approval_request",
        "approval_response", "policy_notice", "selection", "system",
    ] = "system"
    related_offer_id: str | None = None


class Agreement(BaseModel):
    model_config = ConfigDict(frozen=True)

    agreement_id: str
    offer_id: str
    seller_id: str
    product_id: str
    quantity: int
    unit_price_inr: int
    total_price_inr: int
    delivery_days: int
    terms: dict[str, Any] = Field(default_factory=dict)
    seller_approval_status: Literal["not_required", "approved"] = "not_required"
    buyer_authorized: bool = False
    version: int = Field(default=1, ge=1)
    integrity: AgreementVersion | None = None


class VerificationResult(BaseModel):
    passed: bool
    mismatches: list[str] = Field(default_factory=list)
    checked_fields: list[str] = Field(default_factory=list)
    stale: bool = False
    replay_detected: bool = False


class NegotiationResult(BaseModel):
    selected_offer: Offer | None = None
    offers: list[Offer] = Field(default_factory=list)
    events: list[str] = Field(default_factory=list)
    decision_trace: list[str] = Field(default_factory=list)
    messages: list[NegotiationMessage] = Field(default_factory=list)
    reason: str = ""
    recovery_actions: list[str] = Field(default_factory=list)
