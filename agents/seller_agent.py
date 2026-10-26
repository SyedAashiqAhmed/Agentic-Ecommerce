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
        market_best_unit_price: int | None = None,
    ) -> Offer:
        policy = self.profile.policies[product.product_id]
        if proposed_price < policy.minimum_price_inr:
            return self._build_offer(
                product, request.quantity, proposed_price, round_number, policy, "rejected",
                "Rejected: proposed price is below the seller's hard minimum.",
            )
        proposed_price = min(proposed_price, product.listed_price_inr)
        accepted_price = proposed_price
        model_message = ""
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
                        f"Buyer proposed: {proposed_price} INR. "
                        f"Public competing best price: {market_best_unit_price or 'not disclosed'} INR. "
                        "If the competing price is above your hard minimum, beat it by a meaningful "
                        "commercial amount when authorized; otherwise hold your current best price and "
                        "make clear that your floor has been reached. Suggest the lowest safe response."
                    ),
                )
                suggested = int(data["counter_unit_price_inr"])
                if policy.minimum_price_inr <= suggested <= product.listed_price_inr:
                    accepted_price = suggested
                model_message = str(data.get("message", "")).strip()
            except (OllamaError, ValueError, TypeError, KeyError):
                pass
        if market_best_unit_price is not None and accepted_price >= market_best_unit_price:
            competitive_price = market_best_unit_price - max(1, min(500, market_best_unit_price // 100))
            if competitive_price >= policy.minimum_price_inr:
                accepted_price = competitive_price
        if market_best_unit_price is not None and accepted_price >= market_best_unit_price:
            market_note = (
                f"Cannot beat the public market price of {market_best_unit_price} INR without "
                "crossing the supplier's authorized commercial boundary."
            )
        else:
            market_note = (
                f"Supplier position improves on the public market price of "
                f"{market_best_unit_price} INR."
                if market_best_unit_price is not None
                else "No competing market price was disclosed."
            )
        delivery_note = market_note + " Delivery request accepted."
        if requested_delivery_days is not None and requested_delivery_days < product.delivery_days:
            delivery_note = (
                market_note + " "
                f"Delivery request of {requested_delivery_days} days declined; "
                f"verified seller delivery remains {product.delivery_days} days."
            )
        return self._build_offer(
            product, request.quantity, accepted_price, round_number, policy, "proposed",
            delivery_note, model_message,
        )

    def generate_dialogue(
        self,
        *,
        context: str,
        purpose: str,
        proposal: dict[str, object] | None = None,
    ) -> dict[str, str]:
        if not self.llm:
            raise OllamaError("Gemma is required for supplier dialogue")
        system_prompt = (
                "You are an independent Supplier Agent in a real commercial negotiation. "
                "Write the actual message you will send to the buyer or seller approver. "
                "Use only disclosed facts and your authorized proposal. Never reveal private minimums. "
                "The authorized proposal is authoritative: repeat every number and term exactly, and never "
                "invent, change, accept, reject, or promise a commercial term that is not in it. Never claim "
                "a delivery change, discount, approval, stock level, product specification, or trade-off unless "
                "the structured context explicitly supports it. Match the message type exactly: an offer "
                "proposes terms, a clarification only clarifies, a concession explains an actual change, "
                "a rejection refuses the proposal, and an approval request asks the human approver. "
                "If no proposal is provided, acknowledge the "
                "message without asserting new commercial facts. Return JSON with message and rationale strings. "
                "Do not return chain-of-thought."
            )
        for attempt in range(2):
            data = self.llm.generate_json(
                system_prompt,
                f"Purpose: {purpose}\nContext: {context}\nAuthorized proposal: {proposal or {}}\n"
                + ("Return both non-empty JSON strings now." if attempt else ""),
            )
            message = str(data.get("message", "")).strip()
            rationale = str(data.get("rationale", "")).strip()
            if message and rationale:
                return {"message": message, "rationale": rationale}
        raise OllamaError("Gemma returned incomplete supplier dialogue")

    def negotiate(self, context: str) -> dict[str, object]:
        if not self.llm:
            raise OllamaError("Gemma is required for supplier negotiation")
        data = self.llm.generate_json(
            (
                "You are the autonomous Supplier Agent. Decide your next commercial negotiation action "
                "from the current state. Return JSON with action, message, rationale, and proposal. "
                "action must be one of offer, counteroffer, clarification, rejection, concession, walk_away. "
                "proposal must be an object or null with unit_price_inr, quantity, delivery_days. "
                "Never disclose private minimums, exceed inventory, promise impossible delivery, or price "
                "below your authorized minimum. The message must be your actual message to the recipient, "
                "not a rewritten script."
            ),
            context,
        )
        action = str(data.get("action", "")).strip().lower()
        action = {
            "propose": "offer",
            "counter_offer": "counteroffer",
            "counter-offer": "counteroffer",
            "accept": "offer",
            "agree": "offer",
            "decline": "rejection",
            "withdraw": "walk_away",
            "continue": "counteroffer",
            "negotiate": "counteroffer",
        }.get(action, action)
        if action not in {"offer", "counteroffer", "clarification", "rejection", "concession", "walk_away"}:
            raise OllamaError(f"Gemma returned an invalid supplier action: {action or '<empty>'}")
        message = str(data.get("message", "")).strip()
        rationale = str(data.get("rationale", "")).strip()
        proposal = data.get("proposal")
        if not message or not rationale or (proposal is not None and not isinstance(proposal, dict)):
            raise OllamaError("Gemma returned an incomplete supplier action")
        return {
            "action": action,
            "message": message,
            "rationale": rationale,
            "proposal": proposal,
            "_audit": self.llm.last_audit,
        }

    def _build_offer(
        self,
        product: Product,
        quantity: int,
        unit_price: int,
        round_number: int,
        policy: SellerPolicy,
        status: str = "proposed",
        negotiation_note: str = "",
        model_message: str = "",
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
            terms={
                "seller_instructions": policy.seller_instructions,
                "negotiation_note": negotiation_note,
                "model_message": model_message,
            },
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
