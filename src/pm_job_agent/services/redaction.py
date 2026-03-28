"""PII redaction utility — strips contact details before any text is written to disk.

This is a pure function with no LLM dependency; test it independently.

Patterns covered:
  - Email addresses
  - North American phone numbers (various formats)
  - Street addresses (number + street name + type suffix)

Limitations: regex catches structured patterns only. Prose-style contact info
("call me at five five five...") is handled upstream by the generation system
prompt instructing the LLM to omit contact details entirely.
"""

from __future__ import annotations

import re
from typing import Final

_EMAIL: Final = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}", re.IGNORECASE)

# Matches: (555) 123-4567 | 555-123-4567 | 555.123.4567 | +15551234567 | 15551234567
_PHONE: Final = re.compile(
    r"(\+?1[\s.-]?)?"          # optional country code
    r"(\(?\d{3}\)?)"            # area code
    r"[\s.-]"                   # separator
    r"\d{3}"                    # exchange
    r"[\s.-]"                   # separator
    r"\d{4}"                    # subscriber
)

# Matches: 123 Main Street | 45 Oak Ave | 7 Elm Blvd
_ADDRESS: Final = re.compile(
    r"\d+\s+"
    r"(?:[A-Z][a-z]+\s+){1,3}"  # one to three capitalised words (street name)
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Boulevard|Blvd|Lane|Ln|Way|Court|Ct)\.?",
    re.IGNORECASE,
)

_PLACEHOLDER: Final = "[REDACTED]"
_PATTERNS: Final = [_EMAIL, _PHONE, _ADDRESS]


def redact_pii(text: str) -> str:
    """Replace email addresses, phone numbers, and street addresses with [REDACTED]."""
    for pattern in _PATTERNS:
        text = pattern.sub(_PLACEHOLDER, text)
    return text
