from enum import StrEnum


class ActivationStatus(StrEnum):
    PENDING = "pending"  # checklist not finished
    ACTIVE = "active"  # paid tickets can be sold
    SUSPENDED = "suspended"  # stopped by a platform admin


class ChecklistItem(StrEnum):
    """The five steps of SRS 3.2, in order."""

    PAID_TICKET_TYPE = "paid_ticket_type"
    IDENTITY_VERIFIED = "identity_verified"
    ACTIVATION_FEE_PAID = "activation_fee_paid"
    PAYOUT_ACCOUNT = "payout_account"
    TERMS_ACCEPTED = "terms_accepted"


# Bump when the paid-event terms text changes; acceptance records the version
CURRENT_TERMS_VERSION = "2026-11"
