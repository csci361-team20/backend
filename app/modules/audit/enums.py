from enum import StrEnum


class AuditAction(StrEnum):
    """What happened. Grouped by the area it belongs to."""

    # Events
    EVENT_CREATED = "event.created"
    EVENT_UPDATED = "event.updated"
    EVENT_PUBLISHED = "event.published"
    EVENT_UNPUBLISHED = "event.unpublished"
    EVENT_CANCELLED = "event.cancelled"
    EVENT_DUPLICATED = "event.duplicated"
    EVENT_IMAGE_ADDED = "event.image_added"
    EVENT_IMAGE_REMOVED = "event.image_removed"
    # Staff
    STAFF_ADDED = "staff.added"
    STAFF_REMOVED = "staff.removed"
    # Ticket types
    TICKET_TYPE_CREATED = "ticket_type.created"
    TICKET_TYPE_UPDATED = "ticket_type.updated"
    TICKET_TYPE_DELETED = "ticket_type.deleted"
    # Orders and payments
    ORDER_CONFIRMED = "order.confirmed"
    ORDER_CANCELLED = "order.cancelled"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    ORDER_REFUNDED = "refund.completed"
    REGISTRATION_CANCELLED = "refund.registration_cancelled"
    # Organizers
    ORGANIZER_VERIFICATION_CHANGED = "organizer.verification_changed"
    ORGANIZER_IDENTITY_SUBMITTED = "organizer.identity_submitted"
    PAYOUT_ACCOUNT_SAVED = "organizer.payout_account_saved"
    # Paid-sales activation
    ACTIVATION_FEE_PAID = "activation.fee_paid"
    ACTIVATION_FEE_FAILED = "activation.fee_failed"
    ACTIVATION_TERMS_ACCEPTED = "activation.terms_accepted"
    PAID_SALES_ACTIVATED = "activation.activated"
    PAID_SALES_SUSPENDED = "activation.suspended"
    PAID_SALES_RESUMED = "activation.resumed"
    # Promotions
    CAMPAIGN_CREATED = "promo.created"
    CAMPAIGN_UPDATED = "promo.updated"
    CAMPAIGN_DISABLED = "promo.disabled"
    # Support
    SUPPORT_CASE_OPENED = "support.opened"
    SUPPORT_CASE_ASSIGNED = "support.assigned"
    SUPPORT_CASE_STATUS_CHANGED = "support.status_changed"
    SUPPORT_CASE_ESCALATED = "support.escalated"
    # Check-in
    TICKET_CHECKED_IN = "check_in.admitted"
    CHECK_IN_UNDONE = "check_in.undone"
    # Platform
    SETTINGS_CHANGED = "platform.settings_changed"
    USER_SUSPENDED = "platform.user_suspended"
    USER_RESTORED = "platform.user_restored"
    EVENT_SUSPENDED = "event.suspended"
    EVENT_RESTORED = "event.restored"
    EVENT_REPORTED = "event.reported"
    REPORT_REVIEWED = "platform.report_reviewed"
    DISPUTE_OPENED = "payment.dispute_opened"
    DISPUTE_RESOLVED = "payment.dispute_resolved"


class AuditEntity(StrEnum):
    EVENT = "event"
    STAFF_ASSIGNMENT = "staff_assignment"
    TICKET_TYPE = "ticket_type"
    ORDER = "order"
    PAYMENT = "payment"
    ORGANIZER_PROFILE = "organizer_profile"
    EVENT_IMAGE = "event_image"
    PAYOUT_ACCOUNT = "payout_account"
    EVENT_ACTIVATION = "event_activation"
    PLATFORM_SETTINGS = "platform_settings"
    TICKET = "ticket"
    CAMPAIGN = "campaign"
    SUPPORT_CASE = "support_case"
    USER = "user"
    EVENT_REPORT = "event_report"
    DISPUTE = "dispute"


class ActivityArea(StrEnum):
    """Timeline filter: the part before the dot in ``AuditAction``."""

    EVENT = "event"
    STAFF = "staff"
    TICKET_TYPE = "ticket_type"
    ORDER = "order"
    PAYMENT = "payment"
    ACTIVATION = "activation"
    CHECK_IN = "check_in"
    REFUND = "refund"
    PROMO = "promo"
    SUPPORT = "support"
