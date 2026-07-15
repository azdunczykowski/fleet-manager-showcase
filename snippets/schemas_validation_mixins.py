from __future__ import annotations

import re
import unicodedata
from typing import Optional

from pydantic import ValidationInfo, field_validator

# Note: this file is excerpted from a larger mixins.py (678 lines) covering
# validation for every input field shared across schemas — only three
# mixins are shown here as representative examples.



class NameValidationMixin:
    """
    Validates and normalizes first_name and last_name fields.

    Applies Unicode NFKC normalization, enforces length (2–50 chars),
    restricts to letters (including Polish characters), spaces, hyphens,
    and apostrophes, then title-cases the result.
    """

    @field_validator("first_name", "last_name", check_fields=False)
    @classmethod
    def validate_name(cls, v: Optional[str], info: ValidationInfo) -> Optional[str]:
        """Normalize and validate a name field.

        Strips whitespace, applies NFKC normalization, enforces length
        and character restrictions, then title-cases the value.
        Returns None if the input is None.
        """
        if v is None:
            return v

        stripped = v.strip()
        field_name = info.field_name or "name"
        normalized = unicodedata.normalize("NFKC", stripped)

        if not normalized:
            raise ValueError(f"{field_name}.required")

        if len(normalized) < 2:
            raise ValueError(f"{field_name}.too_short")

        if len(normalized) > 50:
            raise ValueError(f"{field_name}.too_long")

        if not re.match(r"^[a-zA-ZąćęłńóśźżĄĆĘŁŃÓŚŹŻ\s'-]+$", normalized):
            raise ValueError(f"{field_name}.invalid_format")

        return normalized.title()


class PhoneNumberValidationMixin:
    """
    Validates and normalizes the phone_number field.

    Strips spaces and dashes, then checks that the result matches
    the expected format: optional + prefix followed by 9–15 digits.
    """

    @field_validator("phone_number", check_fields=False)
    @classmethod
    def validate_phone_number(cls, v: Optional[str]) -> Optional[str]:
        """Normalize and validate the phone number.

        Strips spaces and dashes. Enforces length (10–20 chars after
        normalization) and regex format check.
        Returns None if the input is None.
        """
        if v is None:
            return v

        if not v:
            raise ValueError("user.phone.required")

        normalized = v.strip().replace(" ", "").replace("-", "")

        if len(normalized) < 9:
            raise ValueError("user.phone.too_short")

        if len(normalized) > 20:
            raise ValueError("user.phone.too_long")

        if not re.match(r"^\+?[0-9]{9,15}$", normalized):
            raise ValueError("user.phone.invalid_format")

        return normalized


class IbanValidationMixin:
    """
    Validates and normalizes the iban field.

    Strips spaces, uppercases, enforces length (15–34 chars),
    checks structural format (2-letter country code, 2-digit check digits,
    alphanumeric BBAN), and verifies the MOD-97 checksum.
    Returns None if not provided.
    """

    @field_validator("iban", check_fields=False)
    @classmethod
    def validate_iban(cls, v: Optional[str]) -> Optional[str]:
        """Normalize and validate IBAN format and checksum.

        Strips spaces and uppercases. Validates length, structural format,
        and MOD-97 checksum. Returns None if not provided.
        """
        if v is None:
            return v

        normalized = v.replace(" ", "").upper()

        if len(normalized) < 15 or len(normalized) > 34:
            raise ValueError("iban.invalid_length")

        if not normalized[:2].isalpha() or not normalized[2:4].isdigit():
            raise ValueError("iban.invalid_format")

        if not normalized[4:].isalnum():
            raise ValueError("iban.invalid_format")

        if not _iban_mod97(normalized):
            raise ValueError("iban.invalid_checksum")

        return normalized

# ... (PostalCodeValidationMixin and others follow the same pattern)
