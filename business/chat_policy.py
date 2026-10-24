from schemas import BuyerRequest, Offer, Product, SellerPolicy


def validate_chat_proposal(
    proposal: dict,
    request: BuyerRequest,
    current_offer: Offer,
    product: Product,
    seller_policy: SellerPolicy,
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    price = proposal.get("unit_price_inr", current_offer.unit_price_inr)
    quantity = proposal.get("quantity", current_offer.quantity)
    delivery = proposal.get("delivery_days", current_offer.delivery_days)
    if not isinstance(price, int) or price <= 0:
        errors.append("unit_price_inr must be a positive integer")
    elif price < seller_policy.minimum_price_inr:
        errors.append("price is below the seller hard minimum")
    elif isinstance(quantity, int) and price * quantity > request.max_budget_inr:
        errors.append("total price exceeds the buyer budget")
    if not isinstance(quantity, int) or quantity <= 0 or quantity > product.stock:
        errors.append("quantity exceeds available stock")
    if not isinstance(delivery, int) or delivery < 0:
        errors.append("delivery_days must be a non-negative integer")
    return not errors, errors
