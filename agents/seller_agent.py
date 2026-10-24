from datetime import datetime, timedelta, timezone
from uuid import uuid4

from llm.ollama_client import OllamaClient, OllamaError
from schemas import BuyerRequest, Offer, Product, SellerPolicy, SellerProfile


class SellerAgent:
    def __init__(self, profile: SellerProfile, llm: OllamaClient | None = None) -> None:
        self.profile = profile
        self.llm = llm

    def create_offer(self, request: BuyerRequest, product: Product) -> Offer | None:
        if product.product_id not in self.profile.policies:
            return None
        policy = self.profile.policies[product.product_id]
        if product.stock < request.quantity:
            return None
        if request.delivery_deadline_days is not None and product.delivery_days > request.delivery_deadline_days:
            return None
        return self._build_offer(product, request.quantity, product.listed_price_inr, 1, policy)

    def request_direct_chat(self, request: BuyerRequest, product: Product, offer: Offer) -> str | None:
        if not self.llm:
            return None
        policy = self.profile.policies[product.product_id]
        try:
            data = self.llm.generate_json(
                (
                    "You are an independent supplier agent. Decide whether direct buyer contact "
                    "would clarify a real commercial issue. Return JSON with request_contact (boolean), "
                    "reason (string), and topics (array of strings). Do not request contact merely to chat."
                ),
                (
                    f"Supplier: {self.profile.display_name}. Product: {product.name}. "
                    f"Offer: {offer.unit_price_inr} INR/unit, {offer.delivery_days} days. "
                    f"Hard minimum: {policy.minimum_price_inr} INR. "
                    f"Seller instructions: {policy.seller_instructions}. "
                    f"Buyer request: {request.original_text}"
                ),
            )
            if data.get("request_contact") is True:
                reason = str(data.get("reason", "")).strip()
                topics = data.get("topics", [])
                topic_text = ", ".join(str(topic) for topic in topics[:3])
                if reason:
                    return f"{reason}" + (f" Topics to clarify: {topic_text}." if topic_text else "")
        except (OllamaError, ValueError, TypeError, KeyError):
            return None
        return None

    def respond_to_counteroffer(
        self,
        request: BuyerRequest,
        product: Product,
        proposed_price: int,
        round_number: int,
        requested_delivery_days: int | None = None,
    ) -> Offer:
        policy = self.profile.policies[product.product_id]
        if proposed_price < policy.minimum_price_inr:
            return self._build_offer(
                product, request.quantity, proposed_price, round_number, policy, "rejected",
                "Rejected: proposed price is below the seller's hard minimum.",
            )
        proposed_price = min(proposed_price, product.listed_price_inr)
        accepted_price = proposed_price
        if self.llm:
            try:
                data = self.llm.generate_json(
                    (
                        "You are a seller negotiation agent. Return only JSON with one integer field: "
                        "counter_unit_price_inr. Never return a price below the hard minimum."
                    ),
                    (
                        f"Listed price: {product.listed_price_inr} INR. "
                        f"Hard minimum: {policy.minimum_price_inr} INR. "
                        f"Automatic approval floor: {policy.automatic_approval_floor_inr} INR. "
                        f"Buyer proposed: {proposed_price} INR. Suggest the lowest safe response."
                    ),
                )
                suggested = int(data["counter_unit_price_inr"])
                if policy.minimum_price_inr <= suggested <= product.listed_price_inr:
                    accepted_price = suggested
            except (OllamaError, ValueError, TypeError, KeyError):
                pass
        delivery_note = "Delivery request accepted."
        if requested_delivery_days is not None and requested_delivery_days < product.delivery_days:
            delivery_note = (
                f"Delivery request of {requested_delivery_days} days declined; "
                f"verified seller delivery remains {product.delivery_days} days."
            )
        return self._build_offer(product, request.quantity, accepted_price, round_number, policy, "proposed", delivery_note)

    def _build_offer(
        self,
        product: Product,
        quantity: int,
        unit_price: int,
        round_number: int,
        policy: SellerPolicy,
        status: str = "proposed",
        negotiation_note: str = "",
    ) -> Offer:
        requires_approval = unit_price < policy.automatic_approval_floor_inr
        return Offer(
            offer_id=str(uuid4()),
            seller_id=self.profile.seller_id,
            product_id=product.product_id,
            quantity=quantity,
            unit_price_inr=unit_price,
            total_price_inr=unit_price * quantity,
            delivery_days=product.delivery_days,
            terms={"seller_instructions": policy.seller_instructions, "negotiation_note": negotiation_note},
            round_number=round_number,
            status=status,
            requires_seller_approval=requires_approval,
            seller_approval_status="pending" if requires_approval else "not_required",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )

    def approve(self, offer: Offer) -> Offer:
        if not offer.requires_seller_approval:
            return offer
        return offer.model_copy(update={"seller_approval_status": "approved"})
