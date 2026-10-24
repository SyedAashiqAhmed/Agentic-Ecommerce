from enum import StrEnum


class TransactionState(StrEnum):
    PLANNING = "planning"
    NEGOTIATING = "negotiating"
    APPROVAL_REQUIRED = "approval_required"
    AGREEMENT_ACCEPTED = "agreement_accepted"
    TERMS_CHANGED = "terms_changed"
    PAYMENT_BLOCKED = "payment_blocked"
    RECOVERY_IN_PROGRESS = "recovery_in_progress"
    RECOVERED = "recovered"
    FULFILLED = "fulfilled"
    ESCALATED = "escalated"


class TransactionStateMachine:
    def __init__(self) -> None:
        self.state = TransactionState.PLANNING
        self.history = [self.state.value]

    def transition(self, state: TransactionState) -> None:
        self.state = state
        self.history.append(state.value)
