"""Format checks for Kazakhstan identifiers used by paid-sales activation.

These only check that a number is well formed. They do not prove the number
belongs to the person; the MVP's identity and payout checks are simulated.
"""

import re

_KZ_IBAN = re.compile(r"^KZ\d{2}[0-9A-Z]{16}$")


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def is_valid_kz_iban(value: str) -> bool:
    """A Kazakhstan IBAN (20 characters) with a correct ISO 13616 check sum."""
    iban = normalize_iban(value)
    if not _KZ_IBAN.match(iban):
        return False
    rearranged = iban[4:] + iban[:4]
    digits = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(digits) % 97 == 1


def is_valid_iin_bin(value: str) -> bool:
    """A 12-digit IIN or BIN whose last digit matches the official check digit."""
    if not re.fullmatch(r"\d{12}", value):
        return False
    digits = [int(d) for d in value]
    check = sum(d * w for d, w in zip(digits[:11], range(1, 12), strict=True)) % 11
    if check == 10:
        weights = [3, 4, 5, 6, 7, 8, 9, 10, 11, 1, 2]
        check = sum(d * w for d, w in zip(digits[:11], weights, strict=True)) % 11
        if check == 10:
            return False
    return check == digits[11]


def mask(value: str, visible: int = 4) -> str:
    """``KZ86••••••••••••1234``: enough to recognise, not enough to reuse."""
    if len(value) <= visible + 4:
        return "•" * len(value)
    return value[:4] + "•" * (len(value) - 4 - visible) + value[-visible:]
