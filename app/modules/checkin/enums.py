from enum import StrEnum


class CheckInAction(StrEnum):
    CHECK_IN = "check_in"
    UNDO = "undo"


class CheckInMethod(StrEnum):
    SCAN = "scan"
    MANUAL = "manual"  # found by searching the attendee list


class ScanResult(StrEnum):
    """What the scanner shows (SRS 4.8): one clear outcome per scan."""

    VALID = "valid"  # admitted now (or would be, for a dry-run verify)
    ALREADY_USED = "already_used"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    INVALID = "invalid"  # unreadable, forged, unknown, or not an admission code
    WRONG_EVENT = "wrong_event"  # a real ticket, for a different event


# Check-in staff may reverse their own admissions within this window;
# owners and managers may reverse any admission at any time.
STAFF_UNDO_WINDOW_MINUTES = 10
