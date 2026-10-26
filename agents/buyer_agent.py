import re
from typing import Any

from llm.ollama_client import OllamaClient, OllamaError
from schemas import BuyerRequest, Offer, Product


class BuyerAgent:
    def __init__(self, llm: OllamaClient | None = None) -> None:
        self.llm = llm
        self.last_parse_source = "deterministic fallback"
        self.last_error: str | None = None

    def parse_request(self, text: str) -> BuyerRequest:
        if self.llm:
            try:
                data = self.llm.generate_json(
                    (
                        "You are a strict commerce parser. Return only valid JSON. "
                        "hard_constraints must be an object mapping attribute names to values. "
                        "For minimums use keys such as ram_gb_min and gpu_min. "
                        "Example: {\"product_category\":\"laptop\",\"quantity\":1,"
                        "\"max_budget_inr\":70000,\"delivery_deadline_days\":null,"
                        "\"hard_constraints\":{\"ram_gb_min\":16,\"gpu_min\":\"RTX 3050\"},"
                        "\"preferences\":[\"rating\"]}"
                    ),
                    (
                        "Return fields product_category, quantity, max_budget_inr, "
                        "delivery_deadline_days, hard_constraints, preferences. "
                        f"Request: {text}"
                    ),
                )
                data = self._normalize_llm_data(data, text)
                data["original_text"] = text
                request = BuyerRequest.model_validate(data)
                self.last_parse_source = "Gemma 3 4B via Ollama"
                self.last_error = None
                return request
            except (OllamaError, ValueError, TypeError) as exc:
                self.last_error = str(exc)
        return self._fallback_parse(text)

    @staticmethod
    def _normalize_llm_data(data: dict[str, Any], text: str = "") -> dict[str, Any]:
        explicit_budget = BuyerAgent._extract_budget(text)
        if explicit_budget is not None:
            data["max_budget_inr"] = explicit_budget
        constraints = data.get("hard_constraints", {})
        if isinstance(constraints, list):
            normalized: dict[str, Any] = {}
            for item in constraints:
                text = str(item)
                ram_match = re.search(r"(\d+)\s*gb", text.lower())
                gpu_match = re.search(r"(rtx\s*\d+(?:\s*(?:ti|super))?)", text.lower())
                if ram_match:
                    normalized["ram_gb_min"] = int(ram_match.group(1))
                if gpu_match:
                    normalized["gpu_min"] = gpu_match.group(1).upper()
            data["hard_constraints"] = normalized
        elif isinstance(constraints, dict):
            data["hard_constraints"] = {
                key: value for key, value in constraints.items() if value is not None
            }
        return data

    def filter_products(self, request: BuyerRequest, products: list[Product]) -> list[Product]:
        return [product for product in products if self._meets_constraints(request, product)]

    def meets_hard_requirements(self, request: BuyerRequest, product: Product) -> bool:
        """Check product, stock, delivery, and hard attributes without applying price."""
        if product.stock < request.quantity:
            return False
        if request.delivery_deadline_days is not None and product.delivery_days > request.delivery_deadline_days:
            return False
        return all(
            self._constraint_is_met(product, key, expected)
            for key, expected in request.hard_constraints.items()
        )

    def rank_offers(self, request: BuyerRequest, offers: list[Offer], products: dict[str, Product]) -> list[Offer]:
        valid = [
            offer for offer in offers
            if offer.total_price_inr <= request.max_budget_inr
            and (request.delivery_deadline_days is None or offer.delivery_days <= request.delivery_deadline_days)
        ]
        return sorted(valid, key=lambda offer: self.score_offer(request, offer, products), reverse=True)

    def score_offer(self, request: BuyerRequest, offer: Offer, products: dict[str, Product]) -> float:
        product = products[offer.product_id]
        price_score = max(0.0, 1 - (offer.total_price_inr / request.max_budget_inr))
        rating_score = product.rating / 5
        review_score = min(1.0, product.review_count / 2000)
        delivery_score = 1 / (1 + offer.delivery_days)
        return (price_score * 0.35) + (rating_score * 0.30) + (review_score * 0.20) + (delivery_score * 0.15)

    def propose_tradeoff(self, request: BuyerRequest, offer: Offer, product: Product) -> dict[str, Any] | None:
        target = min(
            request.max_budget_inr // request.quantity,
            int(offer.unit_price_inr * 0.95),
        )
        if target >= offer.unit_price_inr:
            return None
        if self.llm:
            try:
                data = self.llm.generate_json(
                    (
                        "You are a buyer negotiation agent. Return only JSON with fields "
                        "proposed_unit_price_inr, requested_delivery_days, rationale. "
                        "Never exceed the buyer budget or request an impossible delivery date. "
                        "This is a counteroffer, not an acceptance: never say that the buyer accepts "
                        "or agrees to the current seller terms."
                    ),
                    (
                        f"Buyer maximum total budget: {request.max_budget_inr} INR. "
                        f"Quantity: {request.quantity}. Current unit price: {offer.unit_price_inr} INR. "
                        f"Product: {product.name}. Current delivery: {offer.delivery_days} days. "
                        "Try to improve price and delivery, but do not invent guarantees."
                    ),
                )
                proposed = int(data["proposed_unit_price_inr"])
                requested_delivery = int(data.get("requested_delivery_days", offer.delivery_days))
                if 0 < proposed < offer.unit_price_inr and proposed * request.quantity <= request.max_budget_inr:
                    return {
                        "unit_price_inr": proposed,
                        "delivery_days": max(0, requested_delivery),
                        "rationale": str(data.get("rationale", "Requesting a better total value.")),
                        "message": str(data.get("message", "")).strip(),
                    }
            except (OllamaError, ValueError, TypeError, KeyError):
                pass
        return {
            "unit_price_inr": target,
            "delivery_days": max(0, offer.delivery_days - 1),
            "rationale": "Requesting a lower price and one-day delivery improvement.",
            "message": "",
        }

    def generate_dialogue(
        self,
        *,
        context: str,
        purpose: str,
        proposal: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        if not self.llm:
            raise OllamaError("Gemma is required for buyer dialogue")
        system_prompt = (
                "You are the Buyer Agent in a real commercial negotiation. "
                "Write the actual message you will send to the named recipient. "
                "Use only facts in the context and structured proposal. Do not reveal hidden supplier policies. "
                "The structured proposal is authoritative: repeat every number and term exactly, and never "
                "invent, change, accept, reject, or request a commercial term that is not supported by it. "
                "Match the message type exactly: a clarification asks or confirms facts without accepting; "
                "a counteroffer proposes a change and must not say accepted/agreed; a selection compares "
                "packages without accepting; an acceptance is the only type allowed to accept terms. "
                "If no proposal is provided, ask a neutral clarification without asserting new product, price, "
                "delivery, stock, warranty, or approval facts. Return JSON with message and rationale strings. "
                "Do not return chain-of-thought."
            )
        for attempt in range(2):
            data = self.llm.generate_json(
                system_prompt,
                f"Purpose: {purpose}\nContext: {context}\nStructured proposal: {proposal or {}}\n"
                + (
                    "Return both non-empty JSON strings now and correct the message type exactly."
                    if attempt else ""
                ),
            )
            message = str(data.get("message", "")).strip()
            rationale = str(data.get("rationale", "")).strip()
            lower_message = message.lower()
            acceptance_words = re.search(r"\b(accept|acceptance|agree|agreed|approve)\b", lower_message)
            wrong_acceptance = purpose in {"request", "clarification", "counteroffer", "selection"} and acceptance_words
            missing_acceptance = purpose == "acceptance" and not acceptance_words
            if message and rationale and not wrong_acceptance and not missing_acceptance:
                return {"message": message, "rationale": rationale}
        raise OllamaError("Gemma returned incomplete buyer dialogue")

    def negotiate(self, context: str) -> dict[str, Any]:
        if not self.llm:
            raise OllamaError("Gemma is required for buyer negotiation")
        data = self.llm.generate_json(
            (
                "You are the autonomous Buyer Agent. Decide your next negotiation action from the "
                "current state. Return JSON with action, message, rationale, and proposal. "
                "action must be one of request, counteroffer, selection, acceptance, rejection, walk_away. "
                "proposal must be an object or null with only unit_price_inr, quantity, delivery_days. "
                "Never relax hard requirements, exceed budget, invent supplier facts, or accept during a "
                "counteroffer. The message must be your actual message to the recipient, not a template."
            ),
            context,
        )
        action = str(data.get("action", "")).strip().lower()
        action = {
            "propose": "counteroffer",
            "counter_offer": "counteroffer",
            "counter-offer": "counteroffer",
            "accept": "acceptance",
            "agree": "acceptance",
            "compare": "selection",
            "decline": "rejection",
            "withdraw": "walk_away",
            "continue": "counteroffer",
            "negotiate": "counteroffer",
        }.get(action, action)
        if action not in {"request", "counteroffer", "selection", "acceptance", "rejection", "walk_away"}:
            raise OllamaError(f"Gemma returned an invalid buyer action: {action or '<empty>'}")
        message = str(data.get("message", "")).strip()
        rationale = str(data.get("rationale", "")).strip()
        proposal = data.get("proposal")
        if not message or not rationale or (proposal is not None and not isinstance(proposal, dict)):
            raise OllamaError("Gemma returned an incomplete buyer action")
        return {
            "action": action,
            "message": message,
            "rationale": rationale,
            "proposal": proposal,
            "_audit": self.llm.last_audit,
        }

    def propose_counteroffer(self, request: BuyerRequest, offer: Offer, product: Product) -> int | None:
        tradeoff = self.propose_tradeoff(request, offer, product)
        return tradeoff["unit_price_inr"] if tradeoff else None

    def _meets_constraints(self, request: BuyerRequest, product: Product) -> bool:
        if product.stock < request.quantity:
            return False
        if product.listed_price_inr * request.quantity > request.max_budget_inr:
            return False
        if request.delivery_deadline_days is not None and product.delivery_days > request.delivery_deadline_days:
            return False
        for key, expected in request.hard_constraints.items():
            if not self._constraint_is_met(product, key, expected):
                return False
        return True

    def _constraint_is_met(self, product: Product, key: str, expected: Any) -> bool:
        if key.endswith("_min"):
            actual = product.attributes.get(key[:-4])
            if actual is None:
                return False
            if key == "gpu_min":
                return self._gpu_level(str(actual)) >= self._gpu_level(str(expected))
            return actual >= expected
        return product.attributes.get(key) == expected

    @staticmethod
    def _gpu_level(value: str) -> tuple[int, int]:
        match = re.search(r"(\d+)(?:\s*(ti|super))?", value.lower())
        if not match:
            return (0, 0)
        suffix_rank = {"": 0, "super": 1, "ti": 2}
        return int(match.group(1)), suffix_rank.get(match.group(2) or "", 0)

    def _fallback_parse(self, text: str) -> BuyerRequest:
        lower = text.lower()
        explicit_budget = self._extract_budget(text)
        ram_match = re.search(r"(\d+)\s*gb\s*(?:ram)?", lower)
        quantity_match = re.search(r"(\d+)\s*(?:units?|pieces?)", lower)
        category = re.split(r"\b(?:under|below|max(?:imum)?|budget)\b", lower, maxsplit=1)[0].strip(" ,.")
        category = re.sub(r"^(?:i\s+need|please\s+get|find|buy|a|an|one)\s+", "", category).strip()
        return BuyerRequest(
            product_category=category or "general product",
            quantity=int(quantity_match.group(1)) if quantity_match else 1,
            max_budget_inr=explicit_budget if explicit_budget is not None else 10**9,
            hard_constraints={"ram_gb_min": int(ram_match.group(1))} if ram_match else {},
            preferences=["rating", "review_count", "delivery_days"],
            original_text=text,
        )

    @staticmethod
    def _extract_budget(text: str) -> int | None:
        match = re.search(
            r"(?:under|below|max(?:imum)?|budget)\s*(?:of\s*)?"
            r"(?:₹|rs\.?|inr)?\s*([\d][\d,]*(?:\.\d+)?)\s*(k|thousand|lakh|lakhs)?",
            text.lower(),
        )
        if not match:
            return None
        amount = float(match.group(1).replace(",", ""))
        multiplier = {"k": 1_000, "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000}
        return int(amount * multiplier.get(match.group(2) or "", 1))
