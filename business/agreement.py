from uuid import uuid4

from schemas import Agreement, Offer
from business.trust import attach_integrity


def record_agreement(offer: Offer, buyer_authorized: bool = False) -> Agreement:
    if offer.requires_seller_approval and offer.seller_approval_status != "approved":
        raise ValueError("Seller approval is required before recording the agreement")
    agreement = Agreement(
        agreement_id=str(uuid4()),
        offer_id=offer.offer_id,
        seller_id=offer.seller_id,
        product_id=offer.product_id,
        quantity=offer.quantity,
        unit_price_inr=offer.unit_price_inr,
        total_price_inr=offer.total_price_inr,
        delivery_days=offer.delivery_days,
        terms=offer.terms,
        seller_approval_status=offer.seller_approval_status,
        buyer_authorized=buyer_authorized,
    )
    return attach_integrity(agreement)
