from schemas import BuyerRequest, NegotiationMessage, NegotiationResult, Offer, Product
from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from business.risk import default_risk_profiles, score_supplier_offer


class NegotiationEngine:
    def __init__(self, buyer: BuyerAgent, max_rounds: int = 3) -> None:
        self.buyer = buyer
        self.max_rounds = max_rounds

    def run(
        self,
        request: BuyerRequest,
        sellers: list[SellerAgent],
        products: dict[str, Product],
    ) -> NegotiationResult:
        events: list[str] = []
        decision_trace: list[str] = []
        messages: list[NegotiationMessage] = [
            NegotiationMessage(
                sender_id="buyer-agent",
                sender_role="buyer_agent",
                message=f"Requesting {request.quantity} unit(s) within a total budget of ₹{request.max_budget_inr:,}.",
                round_number=1,
                message_type="request",
            )
        ]
        offers: list[Offer] = []
        risk_profiles = default_risk_profiles([seller.profile.seller_id for seller in sellers])
        for seller in sellers:
            for product in seller.profile.products:
                if product.product_id not in products:
                    continue
                if product not in self.buyer.filter_products(request, [product]):
                    continue
                offer = seller.create_offer(request, product)
                if offer:
                    offers.append(offer)
                    risk = risk_profiles[offer.seller_id]
                    offer = offer.model_copy(update={
                        "supplier_risk_score": risk.reliability_score,
                    })
                    offers[-1] = offer
                    events.append(f"{seller.profile.display_name} submitted an initial offer.")
                    messages.append(
                        NegotiationMessage(
                            sender_id=seller.profile.seller_id,
                            sender_role="seller_agent",
                            message=(
                                f"Initial offer: ₹{offer.unit_price_inr:,}/unit, "
                                f"{offer.delivery_days}-day delivery. "
                                + ("Seller approval will be required." if offer.requires_seller_approval else "Within delegated authority.")
                            ),
                            round_number=1,
                            message_type="offer",
                            related_offer_id=offer.offer_id,
                        )
                    )
        ranked = sorted(
            self.buyer.rank_offers(request, offers, products),
            key=lambda offer: score_supplier_offer(offer, products[offer.product_id], risk_profiles[offer.seller_id]),
            reverse=True,
        )
        if not ranked:
            messages.append(
                NegotiationMessage(
                    sender_id="system",
                    sender_role="system",
                    message="No supplier returned an offer satisfying the buyer's hard constraints.",
                    round_number=1,
                    message_type="system",
                )
            )
            return NegotiationResult(offers=offers, events=events, decision_trace=decision_trace, messages=messages, reason="No compliant offer is available.")
        selected = ranked[0]
        selected_product = products[selected.product_id]
        decision_trace.append(
            f"Selected by weighted score: rating 30%, reviews 20%, price 35%, delivery 15%."
        )
        decision_trace.append(
            f"Risk screen: supplier reliability {selected.supplier_risk_score:.0%}; "
            "offers with unresolved risk flags are not auto-authorized."
        )
        tradeoff = self.buyer.propose_tradeoff(request, selected, selected_product)
        if tradeoff and selected.round_number < self.max_rounds:
            seller = next(seller for seller in sellers if seller.profile.seller_id == selected.seller_id)
            counter_price = tradeoff["unit_price_inr"]
            events.append(
                f"Buyer Agent countered at ₹{counter_price:,}/unit and requested {tradeoff['delivery_days']} day delivery "
                f"({tradeoff['rationale']})."
            )
            messages.append(
                NegotiationMessage(
                    sender_id="buyer-agent",
                    sender_role="buyer_agent",
                    message=(
                        f"Counteroffer: ₹{counter_price:,}/unit with requested delivery in "
                        f"{tradeoff['delivery_days']} days. {tradeoff['rationale']}"
                    ),
                    round_number=2,
                    message_type="counteroffer",
                    related_offer_id=selected.offer_id,
                )
            )
            response = seller.respond_to_counteroffer(
                request, selected_product, counter_price, selected.round_number + 1, tradeoff["delivery_days"]
            )
            offers.append(response)
            if response.status != "rejected":
                selected = response
                events.append(
                    f"{seller.profile.display_name} responded at ₹{response.unit_price_inr:,}/unit. "
                    f"{response.terms.get('negotiation_note', '')}"
                )
                messages.append(
                    NegotiationMessage(
                        sender_id=seller.profile.seller_id,
                        sender_role="seller_agent",
                        message=(
                            f"Response: ₹{response.unit_price_inr:,}/unit. "
                            f"{response.terms.get('negotiation_note', '')}"
                        ),
                        round_number=response.round_number,
                        message_type="offer",
                        related_offer_id=response.offer_id,
                    )
                )
            else:
                events.append(f"{seller.profile.display_name} rejected the counteroffer below its hard minimum.")
                messages.append(
                    NegotiationMessage(
                        sender_id=seller.profile.seller_id,
                        sender_role="seller_agent",
                        message="Counteroffer rejected because it violates the seller's hard minimum price.",
                        round_number=response.round_number,
                        message_type="policy_notice",
                        related_offer_id=response.offer_id,
                    )
                )
        events.append(f"Buyer Agent selected {selected.seller_id} as the best compliant offer.")
        if selected.requires_seller_approval:
            decision_trace.append("Selected offer crossed the automatic approval floor and is held for seller approval.")
            messages.append(
                NegotiationMessage(
                    sender_id=selected.seller_id,
                    sender_role="seller_agent",
                    message=(
                        f"Approval request: negotiated price ₹{selected.unit_price_inr:,} is below my "
                        "automatic approval floor. Human seller approval is required before agreement."
                    ),
                    round_number=selected.round_number,
                    message_type="approval_request",
                    related_offer_id=selected.offer_id,
                )
            )
        else:
            decision_trace.append("Selected offer is within the seller's automatic approval authority.")
            messages.append(
                NegotiationMessage(
                    sender_id="buyer-agent",
                    sender_role="buyer_agent",
                    message="This offer is within delegated seller authority and can proceed to agreement.",
                    round_number=selected.round_number,
                    message_type="selection",
                    related_offer_id=selected.offer_id,
                )
            )
        return NegotiationResult(
            selected_offer=selected,
            offers=offers,
            events=events,
            decision_trace=decision_trace,
            messages=messages,
            reason="Best compliant offer selected.",
        )
