from enum import StrEnum


class CaseAudience(StrEnum):
    # An attendee asking the event's organizer team
    ATTENDEE = "attendee"
    # An organizer asking the BiletFlow platform team
    ORGANIZER = "organizer"


class CaseCategory(StrEnum):
    TICKET_DELIVERY = "ticket_delivery"
    PAYMENT = "payment"
    REFUND = "refund"
    SEATING = "seating"
    EVENT_INFORMATION = "event_information"
    CHECK_IN = "check_in"
    ACCOUNT = "account"
    ACTIVATION = "activation"
    TECHNICAL = "technical"


# SRS 4.13: organizers ask the platform about account, activation, payment or
# technical issues; attendees ask organizers about their event.
CATEGORIES_BY_AUDIENCE = {
    CaseAudience.ATTENDEE: {
        CaseCategory.TICKET_DELIVERY,
        CaseCategory.PAYMENT,
        CaseCategory.REFUND,
        CaseCategory.SEATING,
        CaseCategory.EVENT_INFORMATION,
        CaseCategory.CHECK_IN,
        CaseCategory.ACCOUNT,
        CaseCategory.TECHNICAL,
    },
    CaseAudience.ORGANIZER: {
        CaseCategory.ACCOUNT,
        CaseCategory.ACTIVATION,
        CaseCategory.PAYMENT,
        CaseCategory.TECHNICAL,
    },
}


class CaseStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    RESOLVED = "resolved"


STATUS_LABELS = {
    CaseStatus.OPEN: "Open",
    CaseStatus.IN_PROGRESS: "In Progress",
    CaseStatus.WAITING_FOR_CUSTOMER: "Waiting for Customer",
    CaseStatus.RESOLVED: "Resolved",
}


class CaseScope(StrEnum):
    """Which cases to list."""

    REQUESTED = "requested"  # cases I opened
    HANDLING = "handling"  # cases I can answer as staff
    ALL = "all"  # both
