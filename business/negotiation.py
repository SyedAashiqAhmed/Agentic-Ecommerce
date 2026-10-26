from schemas import BuyerRequest, NegotiationMessage, NegotiationResult, Offer, Product
from agents.buyer_agent import BuyerAgent
from agents.seller_agent import SellerAgent
from business.risk import default_risk_profiles, score_supplier_offer
from config import NEGOTIATION_MAX_ROUNDS
from llm.ollama_client import OllamaError


class NegotiationEngine:
    def __init__(
        self,
        buyer: BuyerAgent,
        max_rounds: int = NEGOTIATION_MAX_ROUNDS,
        require_llm: bool = False,
    ) -> None:
        self.buyer = buyer
        self.max_rounds = max_rounds
        self.require_llm = require_llm

    def run(
        self,
        request: BuyerRequest,
        sellers: list[SellerAgent],
        products: dict[str, Product],
    ) -> NegotiationResult:
        if self.require_llm:
            return self._run_gemma(request, sellers, products)
        return self._run_legacy(request, sellers, products)

    def _run_legacy(
        self,
        request: BuyerRequest,
        sellers: list[SellerAgent],
        products: dict[str, Product],
    ) -> NegotiationResult:
        if self.require_llm and (
            self.buyer.llm is None or any(seller.llm is None for seller in sellers)
        ):
            raise OllamaError("Gemma is required for live negotiation; Ollama is unavailable.")
        events: list[str] = []
        decision_trace: list[str] = []
        messages: list[NegotiationMessage] = [
            NegotiationMessage(
                sender_id="buyer-agent",
                recipient_id="supplier-network",
                sender_role="buyer_agent",
                message=f"Requesting {request.quantity} unit(s) within a total budget of ₹{request.max_budget_inr:,}.",
                round_number=1,
                message_type="request",
                rationale="Opening request establishes the buyer's hard budget and quantity boundary.",
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
                            recipient_id="buyer-agent",
                            sender_role="seller_agent",
                            message=(
                                f"Initial offer: ₹{offer.unit_price_inr:,}/unit, "
                                f"{offer.delivery_days}-day delivery. "
                                + ("Seller approval will be required." if offer.requires_seller_approval else "Within delegated authority.")
                            ),
                            round_number=1,
                            message_type="offer",
                            related_offer_id=offer.offer_id,
                            proposal={
                                "unit_price_inr": offer.unit_price_inr,
                                "quantity": offer.quantity,
                                "delivery_days": offer.delivery_days,
                                "terms": offer.terms,
                            },
                            rationale="Initial quote based on listed price, available stock, and verified delivery capability.",
                            validation_status="valid",
                        )
                    )
                    messages.append(
                        NegotiationMessage(
                            sender_id=seller.profile.seller_id,
                            recipient_id="buyer-agent",
                            sender_role="seller_agent",
                            message=(
                                f"{seller.profile.display_name} confirms {product.stock} units in stock and "
                                f"can support {product.delivery_days}-day delivery. "
                                "Any deeper discount may require seller approval."
                            ),
                            round_number=1,
                            message_type="clarification",
                            related_offer_id=offer.offer_id,
                            proposal={
                                "product_name": product.name,
                                "stock_available": product.stock,
                                "delivery_days": product.delivery_days,
                                "unit_price_inr": offer.unit_price_inr,
                            },
                            rationale="Discloses only operational facts relevant to evaluating the initial package.",
                            validation_status="valid",
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
        decision_trace.append(
            f"Selected by weighted score: rating 30%, reviews 20%, price 35%, delivery 15%."
        )
        decision_trace.append(
            f"Risk screen: supplier reliability {selected.supplier_risk_score:.0%}; "
            "offers with unresolved risk flags are not auto-authorized."
        )
        # Give every viable supplier one contextual counteroffer round. This creates
        # meaningful parallel bargaining rather than negotiating only with the winner.
        final_candidates: list[Offer] = []
        market_offers = list(ranked)
        for opening in ranked:
            product = products[opening.product_id]
            seller = next(item for item in sellers if item.profile.seller_id == opening.seller_id)
            public_best = min(
                candidate.unit_price_inr
                for candidate in market_offers
                if candidate.seller_id != opening.seller_id
            ) if any(candidate.seller_id != opening.seller_id for candidate in market_offers) else None
            tradeoff = self.buyer.propose_tradeoff(request, opening, product)
            if not tradeoff or opening.round_number >= self.max_rounds:
                final_candidates.append(opening)
                continue
            messages.append(
                NegotiationMessage(
                    sender_id="buyer-agent",
                    recipient_id=seller.profile.seller_id,
                    sender_role="buyer_agent",
                    message=(
                        f"Evaluation for {seller.profile.display_name}: the {product.name} meets the "
                        f"requested specification and has {product.stock} unit(s) available. "
                        f"The current total is ₹{opening.total_price_inr:,}; delivery is {opening.delivery_days} days. "
                        f"Because the buyer prioritizes value without relaxing the hard requirements, "
                        f"I am testing a lower price with a delivery request."
                    ),
                    round_number=2,
                    message_type="clarification",
                    related_offer_id=opening.offer_id,
                    proposal={
                        "unit_price_inr": opening.unit_price_inr,
                        "quantity": opening.quantity,
                        "delivery_days": opening.delivery_days,
                    },
                    rationale="Separates verified fit from negotiable preferences before making a counteroffer.",
                    validation_status="valid",
                    changed_terms=[],
                )
            )
            messages.append(
                NegotiationMessage(
                    sender_id="buyer-agent",
                    recipient_id=seller.profile.seller_id,
                    sender_role="buyer_agent",
                    message=(
                        f"Evaluation: the package meets the product requirements, but the buyer is targeting "
                        f"₹{tradeoff['unit_price_inr']:,}/unit and {tradeoff['delivery_days']}-day delivery. "
                        f"{tradeoff['rationale']}"
                    ),
                    round_number=2,
                    message_type="counteroffer",
                    related_offer_id=opening.offer_id,
                    proposal={
                        "unit_price_inr": tradeoff["unit_price_inr"],
                        "quantity": request.quantity,
                        "delivery_days": tradeoff["delivery_days"],
                        "public_market_best_unit_price": public_best,
                    },
                    rationale=(
                        f"{tradeoff['rationale']} Suppliers may respond competitively to the "
                        f"public best price of ₹{public_best:,}/unit."
                        if public_best is not None else tradeoff["rationale"]
                    ),
                    validation_status="pending",
                    changed_terms=["unit_price_inr", "delivery_days"],
                )
            )
            events.append(
                f"Buyer Agent countered {seller.profile.display_name} at "
                f"₹{tradeoff['unit_price_inr']:,}/unit for {tradeoff['delivery_days']}-day delivery."
            )
            response = seller.respond_to_counteroffer(
                request,
                product,
                tradeoff["unit_price_inr"],
                3,
                tradeoff["delivery_days"],
                market_best_unit_price=public_best,
            )
            offers.append(response)
            market_offers.append(response)
            is_valid = response.status != "rejected" and response.total_price_inr <= request.max_budget_inr
            delivery_changed = response.delivery_days != opening.delivery_days
            price_changed = response.unit_price_inr != opening.unit_price_inr
            messages.append(
                NegotiationMessage(
                    sender_id=seller.profile.seller_id,
                    recipient_id="buyer-agent",
                    sender_role="seller_agent",
                    message=(
                        f"Package response: ₹{response.unit_price_inr:,}/unit, "
                        f"{response.delivery_days}-day delivery. "
                        f"{response.terms.get('negotiation_note', '')}"
                        if is_valid else
                        "Counteroffer rejected: the requested package is outside this supplier's authorized floor."
                    ),
                    round_number=3,
                    message_type="offer" if is_valid else "rejection",
                    related_offer_id=response.offer_id,
                    proposal={
                        "unit_price_inr": response.unit_price_inr,
                        "quantity": response.quantity,
                        "delivery_days": response.delivery_days,
                        "terms": response.terms,
                        "public_market_best_unit_price": public_best,
                    },
                    rationale="Supplier response is constrained by private minimum price and delivery capability.",
                    validation_status="valid" if is_valid else "invalid",
                    changed_terms=[
                        field for field, changed in (
                            ("unit_price_inr", price_changed),
                            ("delivery_days", delivery_changed),
                        ) if changed
                    ],
                )
            )
            if is_valid:
                final_candidates.append(response)
                events.append(
                    f"{seller.profile.display_name} returned a validated package at "
                    f"₹{response.unit_price_inr:,}/unit; delivery remains {response.delivery_days} days."
                )
            else:
                events.append(f"{seller.profile.display_name} rejected the counteroffer at its policy boundary.")

        final_ranked = sorted(
            self.buyer.rank_offers(request, final_candidates, products),
            key=lambda offer: score_supplier_offer(offer, products[offer.product_id], risk_profiles[offer.seller_id]),
            reverse=True,
        )
        if not final_ranked:
            if self.require_llm:
                self._rewrite_agent_dialogue(messages, request, sellers)
            messages.append(
                NegotiationMessage(
                    sender_id="system",
                    recipient_id="buyer-agent",
                    sender_role="system",
                    message="All supplier counteroffers were rejected by deterministic budget or policy validation.",
                    round_number=3,
                    message_type="rejection",
                    rationale="No final package remained after negotiation.",
                    validation_status="invalid",
                )
            )
            if self.require_llm:
                self._rewrite_agent_dialogue(messages, request, sellers)
            return NegotiationResult(
                offers=offers,
                events=events,
                decision_trace=decision_trace,
                messages=messages,
                reason="No compliant package remained after negotiation.",
                current_round=3,
                negotiation_status="no_agreement",
                termination_reason="Every negotiated response failed final deterministic validation.",
            )
        selected = final_ranked[0]
        messages.append(
            NegotiationMessage(
                sender_id="buyer-agent",
                recipient_id="supplier-network",
                sender_role="buyer_agent",
                message=(
                    f"Comparison complete: {len(final_candidates)} package(s) remain within budget and policy. "
                    f"The leading package is {selected.seller_id} at ₹{selected.unit_price_inr:,}/unit, "
                    f"₹{selected.total_price_inr:,} total, with {selected.delivery_days}-day delivery. "
                    "The buyer is not trading away the required product specification."
                ),
                round_number=3,
                message_type="selection",
                related_offer_id=selected.offer_id,
                proposal={
                    "unit_price_inr": selected.unit_price_inr,
                    "quantity": selected.quantity,
                    "delivery_days": selected.delivery_days,
                    "total_price_inr": selected.total_price_inr,
                },
                rationale="Ranks complete packages after validating budget, inventory, delivery, and supplier authority.",
                validation_status="valid",
                changed_terms=[],
            )
        )
        selected_product = products[selected.product_id]
        selected_seller = next(seller for seller in sellers if seller.profile.seller_id == selected.seller_id)
        supplier_chat_request = selected_seller.request_direct_chat(request, selected_product, selected)
        events.append(f"Buyer Agent selected {selected.seller_id} as the best compliant offer.")
        if selected.requires_seller_approval:
            decision_trace.append("Selected offer crossed the automatic approval floor and is held for seller approval.")
            messages.append(
                NegotiationMessage(
                    sender_id=selected.seller_id,
                    recipient_id="seller-human",
                    sender_role="seller_agent",
                    message=(
                        f"Approval request: negotiated price ₹{selected.unit_price_inr:,} is below my "
                        "automatic approval floor. Human seller approval is required before agreement."
                    ),
                    round_number=selected.round_number,
                    message_type="approval_request",
                    related_offer_id=selected.offer_id,
                    rationale="The final price is below the supplier's automatic approval floor.",
                    validation_status="valid",
                )
            )
        else:
            decision_trace.append("Selected offer is within the seller's automatic approval authority.")
            messages.append(
                NegotiationMessage(
                    sender_id="buyer-agent",
                    recipient_id="system",
                    sender_role="buyer_agent",
                    message="This offer is within delegated seller authority and can proceed to agreement.",
                    round_number=selected.round_number,
                    message_type="selection",
                    related_offer_id=selected.offer_id,
                    rationale="The final package satisfies the buyer constraints and seller authority.",
                    validation_status="valid",
                )
            )
        messages.append(
            NegotiationMessage(
                sender_id="buyer-agent",
                recipient_id=selected.seller_id,
                sender_role="buyer_agent",
                message=(
                    f"Buyer accepts the validated package at ₹{selected.unit_price_inr:,}/unit "
                    f"for {selected.quantity} unit(s), total ₹{selected.total_price_inr:,}, "
                    f"with delivery in {selected.delivery_days} days. "
                    "Agreement verification must pass before checkout."
                ),
                round_number=3,
                message_type="acceptance",
                related_offer_id=selected.offer_id,
                proposal={
                    "unit_price_inr": selected.unit_price_inr,
                    "quantity": selected.quantity,
                    "delivery_days": selected.delivery_days,
                    "total_price_inr": selected.total_price_inr,
                },
                rationale="Accepts only the exact validated package; checkout remains separately gated.",
                validation_status="valid",
                changed_terms=[],
            )
        )
        if self.require_llm:
            self._rewrite_agent_dialogue(messages, request, sellers)
        return NegotiationResult(
            selected_offer=selected,
            offers=offers,
            events=events,
            decision_trace=decision_trace,
            messages=messages,
            reason="Best compliant offer selected.",
            supplier_chat_request=supplier_chat_request,
            supplier_chat_status="pending" if supplier_chat_request else "not_requested",
            chat_room_id=selected.offer_id if supplier_chat_request else None,
            current_round=3,
            negotiation_status="agreed",
            termination_reason="Final compliant package selected after parallel supplier negotiation.",
        )

    def _run_gemma(
        self,
        request: BuyerRequest,
        sellers: list[SellerAgent],
        products: dict[str, Product],
    ) -> NegotiationResult:
        """Run a model-directed negotiation; Python only validates state and commercial authority."""
        if self.buyer.llm is None or any(seller.llm is None for seller in sellers):
            raise OllamaError("Gemma is required for live negotiation; Ollama is unavailable.")

        events: list[str] = []
        trace: list[str] = []
        messages: list[NegotiationMessage] = []
        offers: list[Offer] = []
        history: list[str] = []
        current_round = 1

        buyer_context = self._agent_context(
            request=request,
            round_number=current_round,
            sender="buyer-agent",
            recipient="supplier-network",
            history=history,
            state={"stage": "opening", "suppliers": [s.profile.display_name for s in sellers]},
        )
        buyer_action = self.buyer.negotiate(buyer_context)
        messages.append(self._action_message(
            buyer_action, "buyer-agent", "supplier-network", "buyer_agent", current_round,
        ))
        history.append(self._history_line(messages[-1]))

        for seller in sellers:
            eligible = [
                product for product in seller.profile.products
                if product.product_id in products
                and self.buyer.meets_hard_requirements(request, product)
            ]
            if not eligible:
                continue
            product = eligible[0]
            opening = seller.create_offer(request, product)
            if opening is None:
                continue
            offers.append(opening)
            seller_context = self._agent_context(
                request=request,
                round_number=current_round,
                sender=seller.profile.seller_id,
                recipient="buyer-agent",
                history=history,
                state={
                    "stage": "opening_offer",
                    "buyer_message": buyer_action["message"],
                    "product": product.model_dump(),
                    "authorized_opening_terms": opening.model_dump(mode="json"),
                    "public_offers": [],
                },
            )
            action = seller.negotiate(seller_context)
            proposal = self._validated_proposal(
                action.get("proposal"), opening, seller, product, request,
            )
            offer = opening if proposal is None else self._offer_from_proposal(opening, proposal, 1)
            offers[-1] = offer
            message = self._action_message(
                action, seller.profile.seller_id, "buyer-agent", "seller_agent", current_round,
                related_offer_id=offer.offer_id, proposal=proposal or self._offer_terms(offer),
                validation_status="valid" if proposal is not None or action.get("proposal") is None else "invalid",
            )
            messages.append(message)
            history.append(self._history_line(message))
            events.append(f"{seller.profile.display_name} responded with a model-directed opening position.")

        if not offers:
            return NegotiationResult(
                offers=[],
                events=events,
                decision_trace=trace,
                messages=messages,
                reason="No supplier returned a compliant product.",
                current_round=current_round,
                negotiation_status="no_agreement",
                termination_reason="No eligible supplier product passed deterministic requirements.",
            )

        active = list(offers)
        for current_round in range(2, self.max_rounds + 1):
            next_active: list[Offer] = []
            public_state = [self._offer_terms(offer) | {"seller_id": offer.seller_id} for offer in active]
            for offer in active:
                seller = next(item for item in sellers if item.profile.seller_id == offer.seller_id)
                product = products[offer.product_id]
                buyer_context = self._agent_context(
                    request=request,
                    round_number=current_round,
                    sender="buyer-agent",
                    recipient=seller.profile.seller_id,
                    history=history,
                    state={
                        "stage": "competitive_negotiation",
                        "current_offer": self._offer_terms(offer),
                        "public_offers": public_state,
                        "instruction": "Choose the next action for this supplier. Do not accept yet unless the state is final.",
                    },
                )
                buyer_action = self.buyer.negotiate(buyer_context)
                buyer_proposal = buyer_action.get("proposal")
                buyer_message = self._action_message(
                    buyer_action, "buyer-agent", seller.profile.seller_id, "buyer_agent", current_round,
                    related_offer_id=offer.offer_id, proposal=buyer_proposal,
                    validation_status="pending" if buyer_proposal else "valid",
                )
                messages.append(buyer_message)
                history.append(self._history_line(buyer_message))
                if buyer_action["action"] in {"walk_away", "rejection"}:
                    continue
                seller_context = self._agent_context(
                    request=request,
                    round_number=current_round,
                    sender=seller.profile.seller_id,
                    recipient="buyer-agent",
                    history=history,
                    state={
                        "stage": "respond_to_buyer",
                        "buyer_action": buyer_action,
                        "current_offer": self._offer_terms(offer),
                        "public_offers": public_state,
                        "product": product.model_dump(),
                        "supplier_authority": {
                            "automatic_approval_floor_inr": seller.profile.policies[product.product_id].automatic_approval_floor_inr,
                        },
                    },
                )
                seller_action = seller.negotiate(seller_context)
                seller_proposal = self._validated_proposal(
                    seller_action.get("proposal"), offer, seller, product, request,
                )
                valid = seller_proposal is not None
                updated = offer if not valid else self._offer_from_proposal(offer, seller_proposal, current_round)
                if valid:
                    next_active.append(updated)
                    offers.append(updated)
                elif seller_action["action"] not in {"rejection", "walk_away"}:
                    # An invalid model proposal cannot mutate the last valid commercial position.
                    # Keep that position alive while recording the model's failed attempt.
                    next_active.append(offer)
                response = self._action_message(
                    seller_action, seller.profile.seller_id, "buyer-agent", "seller_agent", current_round,
                    related_offer_id=updated.offer_id,
                    proposal=seller_proposal or seller_action.get("proposal"),
                    validation_status="valid" if valid else "invalid",
                )
                messages.append(response)
                history.append(self._history_line(response))
            active = next_active
            if not active:
                break

        if not active:
            return NegotiationResult(
                offers=offers,
                events=events,
                decision_trace=trace,
                messages=messages,
                reason="Negotiation ended without a compliant package.",
                current_round=current_round,
                negotiation_status="no_agreement",
                termination_reason="Every live supplier position failed validation or walked away.",
            )

        ranked = sorted(
            active,
            key=lambda offer: score_supplier_offer(
                offer, products[offer.product_id],
                default_risk_profiles([seller.profile.seller_id for seller in sellers])[offer.seller_id],
            ),
            reverse=True,
        )
        selected = ranked[0]
        selection_context = self._agent_context(
            request=request,
            round_number=current_round,
            sender="buyer-agent",
            recipient="supplier-network",
            history=history,
            state={"stage": "final_selection", "public_offers": [self._offer_terms(o) for o in ranked]},
        )
        selection = self.buyer.negotiate(selection_context)
        selection_message = self._action_message(
            selection, "buyer-agent", "supplier-network", "buyer_agent", current_round,
            related_offer_id=selected.offer_id, proposal=self._offer_terms(selected),
            validation_status="valid",
        )
        messages.append(selection_message)
        history.append(self._history_line(selection_message))
        if selection["action"] not in {"selection", "acceptance"}:
            return NegotiationResult(
                offers=offers,
                events=events,
                decision_trace=trace,
                messages=messages,
                reason="Buyer Gemma did not select a package.",
                current_round=current_round,
                negotiation_status="no_agreement",
                termination_reason="The buyer agent rejected or walked away during final comparison.",
            )
        if selection["action"] == "acceptance":
            acceptance = selection
            messages[-1] = self._action_message(
                acceptance, "buyer-agent", selected.seller_id, "buyer_agent", current_round,
                related_offer_id=selected.offer_id, proposal=self._offer_terms(selected),
                validation_status="valid",
            )
        else:
            acceptance_context = self._agent_context(
                request=request,
                round_number=current_round,
                sender="buyer-agent",
                recipient=selected.seller_id,
                history=history,
                state={"stage": "final_acceptance", "selected_offer": self._offer_terms(selected)},
            )
            acceptance = self.buyer.negotiate(acceptance_context)
            messages.append(self._action_message(
                acceptance, "buyer-agent", selected.seller_id, "buyer_agent", current_round,
                related_offer_id=selected.offer_id, proposal=self._offer_terms(selected),
                validation_status="valid",
            ))
        if acceptance["action"] != "acceptance":
            return NegotiationResult(
                offers=offers,
                events=events,
                decision_trace=trace,
                messages=messages,
                reason="Buyer Gemma did not authorize acceptance.",
                current_round=current_round,
                negotiation_status="no_agreement",
                termination_reason="The buyer agent did not issue an explicit acceptance.",
            )
        seller = next(item for item in sellers if item.profile.seller_id == selected.seller_id)
        chat_request = seller.request_direct_chat(request, products[selected.product_id], selected)
        return NegotiationResult(
            selected_offer=selected,
            offers=offers,
            events=events,
            decision_trace=trace,
            messages=messages,
            reason="Gemma selected a validated supplier package.",
            supplier_chat_request=chat_request,
            supplier_chat_status="pending" if chat_request else "not_requested",
            chat_room_id=selected.offer_id,
            current_round=current_round,
            negotiation_status="agreed",
            termination_reason="Buyer accepted the best validated package after model-directed negotiation.",
        )

    @staticmethod
    def _agent_context(*, request, round_number, sender, recipient, history, state) -> str:
        return (
            f"Buyer request: {request.model_dump()}\n"
            f"Round: {round_number}\nSender: {sender}\nRecipient: {recipient}\n"
            f"Conversation history: {history[-12:]}\nCurrent state: {state}\n"
            "Choose the next action from the actual state. Do not invent unavailable facts."
        )

    @staticmethod
    def _action_message(action, sender, recipient, role, round_number, related_offer_id=None,
                        proposal=None, validation_status="not_checked"):
        audit = action.get("_audit") or {}
        return NegotiationMessage(
            sender_id=sender,
            recipient_id=recipient,
            sender_role=role,
            message=str(action["message"]),
            round_number=round_number,
            message_type=str(action["action"]),
            related_offer_id=related_offer_id,
            proposal=proposal,
            rationale=str(action["rationale"]),
            validation_status=validation_status,
            generated_by="gemma",
            model=audit.get("model"),
            ollama_request_id=audit.get("ollama_request_id"),
            prompt_hash=audit.get("prompt_hash"),
            response_hash=audit.get("response_hash"),
            generated_at=audit.get("generated_at"),
            generation_status="verified" if audit else "failed",
        )

    @staticmethod
    def _history_line(message):
        return f"{message.sender_id} -> {message.recipient_id}: {message.message}"

    @staticmethod
    def _offer_terms(offer):
        return {
            "unit_price_inr": offer.unit_price_inr,
            "quantity": offer.quantity,
            "delivery_days": offer.delivery_days,
            "total_price_inr": offer.total_price_inr,
        }

    @staticmethod
    def _offer_from_proposal(offer, proposal, round_number):
        return offer.model_copy(update={
            "unit_price_inr": proposal["unit_price_inr"],
            "quantity": proposal["quantity"],
            "delivery_days": proposal["delivery_days"],
            "total_price_inr": proposal["unit_price_inr"] * proposal["quantity"],
            "round_number": round_number,
            "requires_seller_approval": False,
        })

    @staticmethod
    def _validated_proposal(proposal, current, seller, product, request):
        if not isinstance(proposal, dict):
            return None
        try:
            unit = int(proposal["unit_price_inr"])
            quantity = int(proposal.get("quantity", request.quantity))
            delivery = int(proposal.get("delivery_days", product.delivery_days))
        except (KeyError, TypeError, ValueError):
            return None
        policy = seller.profile.policies[product.product_id]
        if (
            quantity != request.quantity
            or quantity > product.stock
            or unit < policy.minimum_price_inr
            or unit * quantity > request.max_budget_inr
            or delivery != product.delivery_days
        ):
            return None
        return {"unit_price_inr": unit, "quantity": quantity, "delivery_days": delivery}

    def _rewrite_agent_dialogue(
        self,
        messages: list[NegotiationMessage],
        request: BuyerRequest,
        sellers: list[SellerAgent],
    ) -> None:
        """Have Gemma author every agent-facing sentence after deterministic validation."""
        seller_by_id = {seller.profile.seller_id: seller for seller in sellers}
        history: list[str] = []
        for index, message in enumerate(messages):
            if message.sender_role not in {"buyer_agent", "seller_agent"}:
                continue
            context = (
                f"Buyer request: {request.original_text}\n"
                f"Round: {message.round_number}\n"
                f"Sender: {message.sender_id}\n"
                f"Recipient: {message.recipient_id or 'network'}\n"
                f"Message type: {message.message_type}\n"
                f"Sender role: {message.sender_role}\n"
                f"Validation status: {message.validation_status}\n"
                f"Prior recorded messages:\n" + "\n".join(history[-6:]) +
                f"\nValidated proposal (the only authoritative commercial terms): {message.proposal or {}}\n"
                "Do not add facts that are absent from the request, history, or validated proposal."
            )
            if message.sender_role == "buyer_agent":
                dialogue = self.buyer.generate_dialogue(
                    context=context,
                    purpose=message.message_type,
                    proposal=message.proposal,
                )
            else:
                seller = seller_by_id.get(message.sender_id)
                if seller is None:
                    raise OllamaError(f"Unknown supplier speaker: {message.sender_id}")
                dialogue = seller.generate_dialogue(
                    context=context,
                    purpose=message.message_type,
                    proposal=message.proposal,
                )
            messages[index] = message.model_copy(update={
                "message": dialogue["message"],
                "rationale": dialogue["rationale"],
            })
            history.append(f"{message.sender_id} -> {message.recipient_id or 'network'}: {dialogue['message']}")
