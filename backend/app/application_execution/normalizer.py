"""Deterministic value normalization for advanced form controls (Phase 16).

Normalizes user-provided or profile-derived values to the format expected by
each control type.  Every function is pure, deterministic, and never fabricates
data — it only transforms existing values.
"""
from __future__ import annotations

import re
from datetime import datetime


# ---------------------------------------------------------------------------
# Date normalization
# ---------------------------------------------------------------------------

_DATE_FORMATS = [
    ("%Y-%m-%d", "YYYY-MM-DD"),
    ("%d/%m/%Y", "DD/MM/YYYY"),
    ("%m/%d/%Y", "MM/DD/YYYY"),
    ("%d-%m-%Y", "DD-MM-YYYY"),
    ("%m-%d-%Y", "MM-DD-YYYY"),
    ("%d.%m.%Y", "DD.MM.YYYY"),
    ("%B %d, %Y", "Month DD, YYYY"),
    ("%b %d, %Y", "Mon DD, YYYY"),
    ("%d %B %Y", "DD Month YYYY"),
    ("%d %b %Y", "DD Mon YYYY"),
    ("%Y/%m/%d", "YYYY/MM/DD"),
]


def normalize_date(value: str, target_format: str = "%Y-%m-%d") -> str | None:
    """Parse a date string in any common format and return in *target_format*.

    Returns None if the value cannot be parsed as a date.
    Never fabricates a date — only re-格式 an existing one.
    """
    if not value or not value.strip():
        return None
    v = value.strip()
    for fmt, _label in _DATE_FORMATS:
        try:
            dt = datetime.strptime(v, fmt)
            return dt.strftime(target_format)
        except ValueError:
            continue
    # Last resort: try to extract a YYYY-MM-DD pattern
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return dt.strftime(target_format)
        except ValueError:
            pass
    return None


def detect_date_format(value: str) -> str | None:
    """Return the detected format label (e.g. 'YYYY-MM-DD') or None."""
    if not value or not value.strip():
        return None
    v = value.strip()
    for fmt, label in _DATE_FORMATS:
        try:
            datetime.strptime(v, fmt)
            return label
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Currency normalization
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "₹": "INR",
    "¥": "JPY",
    "C$": "CAD",
    "A$": "AUD",
}


def normalize_currency(value: str) -> tuple[float | None, str | None]:
    """Extract a numeric amount and currency code from a currency string.

    Returns (amount, currency_code).  Never changes the applicant's intended
    amount — only strips formatting.  Returns (None, None) if unparseable.
    """
    if not value or not value.strip():
        return None, None
    v = value.strip()

    # Detect currency symbol
    currency_code = None
    for sym, code in _CURRENCY_SYMBOLS.items():
        if v.startswith(sym):
            currency_code = code
            v = v[len(sym):].strip()
            break

    # Remove thousands separators (commas, spaces) but preserve decimal
    v = re.sub(r"[,\s]", "", v)
    # Handle LPA / Lakh suffix
    v = re.sub(r"\s*(LPA|Lakhs?|lakhs?)$", "", v, flags=re.IGNORECASE).strip()

    try:
        amount = float(v)
        return amount, currency_code
    except ValueError:
        return None, None


def format_currency_for_display(amount: float, currency_code: str | None = None) -> str:
    """Format a numeric amount for display.  Preserves the original number."""
    if amount == int(amount):
        return f"{int(amount):,}"
    return f"{amount:,.2f}"


# ---------------------------------------------------------------------------
# Multi-select normalization
# ---------------------------------------------------------------------------

def normalize_multi_select(
    requested: list[str],
    available_options: list[str],
) -> tuple[list[str], list[str]]:
    """Map requested values to available options.

    Returns (matched, unmatched).  Never invents an option.
    Matching is case-insensitive with token overlap fallback.
    """
    matched: list[str] = []
    unmatched: list[str] = []
    avail_lower = {opt.lower().strip(): opt for opt in available_options}

    for req in requested:
        req_norm = req.lower().strip()
        # Exact match
        if req_norm in avail_lower:
            matched.append(avail_lower[req_norm])
            continue
        # Token containment: check if all tokens of request appear in an option
        req_tokens = set(req_norm.split())
        best_match = None
        best_score = 0.0
        for opt_norm, opt_orig in avail_lower.items():
            opt_tokens = set(opt_norm.split())
            if not req_tokens:
                continue
            overlap = len(req_tokens & opt_tokens) / len(req_tokens)
            if overlap > best_score and overlap >= 0.6:
                best_score = overlap
                best_match = opt_orig
        if best_match:
            matched.append(best_match)
        else:
            unmatched.append(req)
    return matched, unmatched


# ---------------------------------------------------------------------------
# Checkbox / Radio normalization
# ---------------------------------------------------------------------------

def normalize_checkbox_value(value: str) -> bool | None:
    """Normalize a checkbox value to a boolean.

    Returns True for affirmative values, False for negative, None for unknown.
    """
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "yes", "1", "on", "checked", "selected"):
        return True
    if v in ("false", "no", "0", "off", "unchecked", ""):
        return False
    return None


def normalize_radio_value(value: str, options: list[str]) -> str | None:
    """Match a radio value against available options.

    Returns the matched option label or None if not found.
    """
    if not value or not options:
        return None
    v = value.strip().lower()
    for opt in options:
        if opt.strip().lower() == v:
            return opt
    # Token containment fallback
    v_tokens = set(v.split())
    for opt in options:
        opt_tokens = set(opt.strip().lower().split())
        if v_tokens and opt_tokens and v_tokens <= opt_tokens:
            return opt
    return None


# ---------------------------------------------------------------------------
# Autocomplete normalization
# ---------------------------------------------------------------------------

def normalize_autocomplete_input(value: str) -> str:
    """Clean user input before sending to an autocomplete field.

    Strips trailing commas, extra whitespace, and common noise.
    Never truncates the search term.
    """
    if not value:
        return ""
    v = value.strip()
    # Remove trailing comma (common in location fields)
    v = re.sub(r",\s*$", "", v)
    # Collapse multiple spaces
    v = re.sub(r"\s+", " ", v)
    return v


def select_autocomplete_suggestion(
    input_value: str,
    suggestions: list[str],
) -> str | None:
    """Select the best suggestion from a list.

    Returns the exact or best match, or None if ambiguous.
    Never selects if there are multiple close matches.
    """
    if not suggestions:
        return None
    if not input_value:
        return None
    inp = input_value.strip().lower()
    # Exact match first
    for s in suggestions:
        if s.strip().lower() == inp:
            return s
    # Prefix match
    prefix_matches = [s for s in suggestions if s.strip().lower().startswith(inp)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        return None  # ambiguous
    # Token containment
    inp_tokens = set(inp.split())
    token_matches = []
    for s in suggestions:
        s_tokens = set(s.strip().lower().split())
        if inp_tokens and s_tokens and inp_tokens <= s_tokens:
            token_matches.append(s)
    if len(token_matches) == 1:
        return token_matches[0]
    return None  # ambiguous or no match
