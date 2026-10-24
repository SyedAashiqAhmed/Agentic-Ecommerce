import hashlib
import json
from datetime import datetime, timezone

from schemas import Agreement, AgreementVersion, Offer, VerificationResult


def canonical_agreement_json(agreement: Agreement) -> str:
    payload = agreement.model_dump(mode="json", exclude={"integrity"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def agreement_hash(agreement: Agreement) -> str:
    return hashlib.sha256(canonical_agreement_json(agreement).encode("utf-8")).hexdigest()


def attach_integrity(agreement: Agreement) -> Agreement:
    canonical = canonical_agreement_json(agreement)
    integrity = AgreementVersion(
        version=agreement.version,
        canonical_json=canonical,
        sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    return agreement.model_copy(update={"integrity": integrity})


def verify_integrity(agreement: Agreement) -> VerificationResult:
    if agreement.integrity is None:
        return VerificationResult(passed=False, mismatches=["Agreement has no integrity record"])
    actual = agreement_hash(agreement)
    if actual != agreement.integrity.sha256:
        return VerificationResult(
            passed=False,
            mismatches=["Agreement integrity hash does not match its recorded version"],
            checked_fields=["sha256"],
        )
    return VerificationResult(passed=True, checked_fields=["sha256"])


def offer_is_expired(offer: Offer, now: datetime | None = None) -> bool:
    return bool(offer.expires_at and offer.expires_at <= (now or datetime.now(timezone.utc)))
