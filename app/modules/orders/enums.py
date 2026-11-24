from enum import StrEnum


class OrderStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    # Hold ran out before payment; the places went back on sale
    EXPIRED = "expired"


class TicketStatus(StrEnum):
    VALID = "valid"
    CHECKED_IN = "checked_in"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


# Every payment in the academic MVP is simulated; no real money moves (SRS 4.6)
SIMULATED_PROVIDER = "biletflow-simulation"


class RefundStatus(StrEnum):
    # Simulated refunds complete at once; a real provider would add "pending"
    COMPLETED = "completed"
