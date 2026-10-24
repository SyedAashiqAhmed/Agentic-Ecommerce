from schemas import Offer, Product, SupplierRiskProfile


def score_supplier_offer(offer: Offer, product: Product, risk: SupplierRiskProfile) -> float:
    price_score = max(0.0, 1 - offer.total_price_inr / max(product.listed_price_inr * offer.quantity, 1))
    quality_score = (product.rating / 5) * 0.45 + min(product.review_count / 2000, 1) * 0.2
    delivery_score = 1 / (1 + offer.delivery_days) * 0.2
    reliability_score = risk.reliability_score * 0.15
    return price_score * 0.25 + quality_score + delivery_score + reliability_score


def default_risk_profiles(supplier_ids: list[str]) -> dict[str, SupplierRiskProfile]:
    return {
        supplier_id: SupplierRiskProfile(
            supplier_id=supplier_id,
            reliability_score=0.92 if supplier_id.endswith("nova") else 0.78,
            risk_flags=[] if supplier_id.endswith("nova") else ["slower delivery history"],
        )
        for supplier_id in supplier_ids
    }
