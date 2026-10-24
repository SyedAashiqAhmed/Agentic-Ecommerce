from datetime import datetime, timezone

from schemas import Agreement, Offer, VerificationResult


def verify_agreement(agreement: Agreement, current: Offer) -> VerificationResult:
    checks = ["seller_id", "product_id", "quantity", "unit_price_inr", "total_price_inr", "delivery_days", "terms"]
    mismatches: list[str] = []
    stale = bool(current.expires_at and current.expires_at <= datetime.now(timezone.utc))
    for field in checks:
        expected = getattr(agreement, field)
        actual = getattr(current, field)
        if expected != actual:
            mismatches.append(f"{field}: agreed={expected!r}, current={actual!r}")
    if agreement.seller_approval_status == "approved" and current.seller_approval_status != "approved":
        mismatches.append("seller_approval_status: agreement was approved but current approval is missing")
    if stale:
        mismatches.append("offer: current supplier offer has expired")
    return VerificationResult(passed=not mismatches, mismatches=mismatches, checked_fields=checks, stale=stale)
