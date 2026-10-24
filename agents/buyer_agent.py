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
                data = self._normalize_llm_data(data)
                data["original_text"] = text
                request = BuyerRequest.model_validate(data)
                self.last_parse_source = "Gemma 3 4B via Ollama"
                self.last_error = None
                return request
            except (OllamaError, ValueError, TypeError) as exc:
                self.last_error = str(exc)
        return self._fallback_parse(text)

    @staticmethod
    def _normalize_llm_data(data: dict[str, Any]) -> dict[str, Any]:
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
        return data

    def filter_products(self, request: BuyerRequest, products: list[Product]) -> list[Product]:
        return [product for product in products if self._meets_constraints(request, product)]

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
                        "Never exceed the buyer budget or request an impossible delivery date."
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
                    }
            except (OllamaError, ValueError, TypeError, KeyError):
                pass
        return {
            "unit_price_inr": target,
            "delivery_days": max(0, offer.delivery_days - 1),
            "rationale": "Requesting a lower price and one-day delivery improvement.",
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
        budget_match = re.search(r"(?:under|below|max(?:imum)?|budget)[^\d₹]*(\d[\d,]*)", lower)
        ram_match = re.search(r"(\d+)\s*gb\s*(?:ram)?", lower)
        quantity_match = re.search(r"(\d+)\s*(?:units?|pieces?)", lower)
        category = " ".join(text.split()[:3]).strip(" ,.")
        return BuyerRequest(
            product_category=category or "general product",
            quantity=int(quantity_match.group(1)) if quantity_match else 1,
            max_budget_inr=int(budget_match.group(1).replace(",", "")) if budget_match else 10**9,
            hard_constraints={"ram_gb_min": int(ram_match.group(1))} if ram_match else {},
            preferences=["rating", "review_count", "delivery_days"],
            original_text=text,
        )
