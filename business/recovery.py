from dataclasses import dataclass, field

from schemas import Agreement, Offer
from business.trust import attach_integrity, verify_integrity
from business.verification import verify_agreement


@dataclass
class RecoveryManager:
    actions: list[str] = field(default_factory=list)

    def detect_and_recover(self, agreement: Agreement, current: Offer, fallback: Offer | None = None) -> tuple[bool, Agreement | None]:
        integrity = verify_integrity(agreement)
        terms = verify_agreement(agreement, current)
        if integrity.passed and terms.passed:
            return True, agreement
        self.actions.append("Payment authorization blocked because supplier terms changed.")
        if fallback is None:
            self.actions.append("No compliant fallback offer is available; escalated for human review.")
            return False, None
        self.actions.append(f"Recovery resumed with fallback supplier {fallback.seller_id}.")
        recovered = Agreement(
            agreement_id=agreement.agreement_id,
            offer_id=fallback.offer_id,
            seller_id=fallback.seller_id,
            product_id=fallback.product_id,
            quantity=fallback.quantity,
            unit_price_inr=fallback.unit_price_inr,
            total_price_inr=fallback.total_price_inr,
            delivery_days=fallback.delivery_days,
            terms=fallback.terms,
            seller_approval_status=fallback.seller_approval_status if fallback.requires_seller_approval else "not_required",
            version=agreement.version + 1,
        )
        self.actions.append(f"Created agreement amendment version {recovered.version}; prior hash was preserved.")
        return True, attach_integrity(recovered)
