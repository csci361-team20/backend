from enum import StrEnum


class DiscountType(StrEnum):
    PERCENT = "percent"  # 1-100 % off the applicable subtotal
    FIXED = "fixed"  # KZT off the applicable subtotal, once per order
