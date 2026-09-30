import re


class InvalidPhone(ValueError):
    pass


# Optional country prefix (+233 / 233) or trunk 0, then a 9-digit Ghana mobile
# number whose first digit is 2 or 5 (020, 023, 024, 025, 026, 027, 028, 050, 053-059).
_GH_MOBILE = re.compile(r"^(?:\+?233|0)?([25]\d{8})$")


def normalize_gh_number(raw: str) -> str:
    """024xxxxxxx / 24xxxxxxx / 23324xxxxxxx / +23324xxxxxxx  ->  +23324xxxxxxx"""
    cleaned = re.sub(r"[\s\-().]", "", raw or "")
    match = _GH_MOBILE.match(cleaned)
    if not match:
        raise InvalidPhone("Enter a valid Ghana mobile number, like 024 123 4567.")
    return "+233" + match.group(1)


def mask_phone(e164: str) -> str:
    """+233241234567 -> +233 *** *** 567"""
    return f"+233 *** *** {e164[-3:]}"
