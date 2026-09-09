"""Page detection and identification for multi-step forms (Phase 14).

Detects page type (form/review/submission), identifies pages via stable
signals, and detects navigation controls (next/back/review/submit).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.application_execution.base import DetectedField
from app.application_execution.form_session import (
    NavigationAction,
    PageSnapshot,
    PageType,
    TrackedField,
    compute_page_fingerprint,
)

# ---------------------------------------------------------------------------
# Navigation button text patterns
# ---------------------------------------------------------------------------

_NEXT_PATTERNS = [
    re.compile(r"\b(next|continue|proceed|save\s*[&+]\s*continue|save\s+and\s+continue)\b", re.I),
    re.compile(r"\b(continue\s+application|go\s+to\s+next|next\s+step|next\s+page)\b", re.I),
    re.compile(r"\b(save\s*[&+]\s*next|save\s+and\s+next|next\s+question)\b", re.I),
]
_BACK_PATTERNS = [
    re.compile(r"\b(back|previous|go\s+back|previous\s+step)\b", re.I),
]
_REVIEW_PATTERNS = [
    re.compile(
        r"\b(review|review\s+application|review\s*[&+]\s*submit"
        r"|review\s+and\s+submit)\b",
        re.I,
    ),
]
_SUBMIT_PATTERNS = [
    re.compile(
        r"\b(submit|submit\s+application|apply|send\s+application"
        r"|confirm\s+and\s+submit)\b",
        re.I,
    ),
]

# Patterns that indicate a step/progress indicator
_STEP_PATTERNS = [
    re.compile(r"step\s+(\d+)\s+of\s+(\d+)", re.I),
    re.compile(r"page\s+(\d+)\s+of\s+(\d+)", re.I),
    re.compile(r"(\d+)\s*/\s*(\d+)", re.I),
    re.compile(r"part\s+(\d+)\s+of\s+(\d+)", re.I),
]

# Patterns for review page headings
_REVIEW_HEADING_PATTERNS = [
    re.compile(r"review\s+your\s+application", re.I),
    re.compile(r"application\s+summary", re.I),
    re.compile(r"confirm\s+your\s+application", re.I),
    re.compile(r"before\s+you\s+submit", re.I),
    re.compile(r"final\s+review", re.I),
]

# Patterns for submission/confirmation pages
_SUBMISSION_HEADING_PATTERNS = [
    re.compile(r"application\s+submitted", re.I),
    re.compile(r"thank\s+you\s+for\s+applying", re.I),
    re.compile(r"submission\s+confirmation", re.I),
    re.compile(r"application\s+received", re.I),
]

# Consent/declaration patterns
_CONSENT_PATTERNS = [
    re.compile(r"i\s+certify\s+that", re.I),
    re.compile(r"i\s+declare\s+that", re.I),
    re.compile(r"i\s+agree\s+to", re.I),
    re.compile(r"i\s+confirm\s+that", re.I),
    re.compile(r"terms\s+and\s+conditions", re.I),
    re.compile(r"privacy\s+policy", re.I),
    re.compile(r"accuracy\s+of\s+information", re.I),
]


# ---------------------------------------------------------------------------
# Detection results
# ---------------------------------------------------------------------------

@dataclass
class NavigationDetection:
    """Detected navigation controls on a page."""
    action: NavigationAction = NavigationAction.NONE
    has_next: bool = False
    has_back: bool = False
    has_review: bool = False
    has_submit: bool = False
    next_selector: str | None = None
    back_selector: str | None = None
    review_selector: str | None = None
    submit_selector: str | None = None
    next_button_text: str | None = None
    next_disabled: bool = False
    back_disabled: bool = False


@dataclass
class PageClassification:
    """Classification of the current page."""
    page_type: PageType = PageType.UNKNOWN_PAGE
    heading: str | None = None
    step_indicator: str | None = None
    step_current: int | None = None
    step_total: int | None = None
    has_consent: bool = False
    consent_text: str | None = None
    confidence: float = 0.0


@dataclass
class PageIdentification:
    """Stable identification of a form page."""
    url: str = ""
    pathname: str = ""
    heading: str | None = None
    step_indicator: str | None = None
    page_key: str = ""
    fingerprint: str = ""
    field_labels: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Navigation detection
# ---------------------------------------------------------------------------

def _text_matches(text: str | None, patterns: list[re.Pattern]) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in patterns)


def _extract_button_text(element: dict) -> str | None:
    """Extract text from a button element dict."""
    for key in ("text", "label", "aria-label", "title", "value", "innerText"):
        val = element.get(key)
        if val and isinstance(val, str) and val.strip():
            return val.strip()
    return None


def detect_navigation(elements: list[dict]) -> NavigationDetection:
    """Detect navigation controls from a list of button/link elements.

    Each element should have at least: {selector: str, text: str}
    Optional: {disabled: bool, role: str, type: str}
    """
    result = NavigationDetection()
    candidates: list[tuple[NavigationAction, str, str, bool]] = []

    for el in elements:
        text = _extract_button_text(el)
        if not text:
            continue
        selector = el.get("selector", "")
        disabled = el.get("disabled", False)

        if _text_matches(text, _NEXT_PATTERNS):
            candidates.append((NavigationAction.NEXT_PAGE, selector, text, disabled))
        elif _text_matches(text, _REVIEW_PATTERNS):
            candidates.append((NavigationAction.REVIEW, selector, text, disabled))
        elif _text_matches(text, _SUBMIT_PATTERNS):
            candidates.append((NavigationAction.SUBMIT, selector, text, disabled))
        elif _text_matches(text, _BACK_PATTERNS):
            candidates.append((NavigationAction.PREVIOUS_PAGE, selector, text, disabled))

    # Priority: SUBMIT > REVIEW > NEXT > BACK
    for action, selector, text, disabled in candidates:
        if action == NavigationAction.SUBMIT and not result.has_submit:
            result.has_submit = True
            result.submit_selector = selector
        elif action == NavigationAction.REVIEW and not result.has_review:
            result.has_review = True
            result.review_selector = selector
        elif action == NavigationAction.NEXT_PAGE and not result.has_next:
            result.has_next = True
            result.next_selector = selector
            result.next_button_text = text
            result.next_disabled = disabled
        elif action == NavigationAction.PREVIOUS_PAGE and not result.has_back:
            result.has_back = True
            result.back_selector = selector
            result.back_disabled = disabled

    # Determine primary action
    if result.has_submit:
        result.action = NavigationAction.SUBMIT
    elif result.has_review:
        result.action = NavigationAction.REVIEW
    elif result.has_next:
        result.action = NavigationAction.NEXT_PAGE
    elif result.has_back:
        result.action = NavigationAction.PREVIOUS_PAGE

    return result


# ---------------------------------------------------------------------------
# Page classification
# ---------------------------------------------------------------------------

def classify_page(
    heading: str | None = None,
    url: str | None = None,
    field_count: int = 0,
    has_submit_button: bool = False,
    has_next_button: bool = False,
    button_texts: list[str] | None = None,
) -> PageClassification:
    """Classify the current page type based on DOM signals.

    Uses heading, URL, field count, and button configuration to determine
    whether this is a form page, review page, submission page, or unknown.
    """
    result = PageClassification(heading=heading)

    # Extract step indicator from heading
    if heading:
        for pattern in _STEP_PATTERNS:
            m = pattern.search(heading)
            if m:
                result.step_current = int(m.group(1))
                result.step_total = int(m.group(2))
                result.step_indicator = m.group(0)
                break

    # Check for review page
    if heading and _text_matches(heading, _REVIEW_HEADING_PATTERNS):
        result.page_type = PageType.REVIEW_PAGE
        result.confidence = 0.9
        return result

    # Check for submission/confirmation page
    if heading and _text_matches(heading, _SUBMISSION_HEADING_PATTERNS):
        result.page_type = PageType.SUBMISSION_PAGE
        result.confidence = 0.9
        return result

    # Check for consent/declaration text
    if button_texts:
        for text in button_texts:
            if _text_matches(text, _CONSENT_PATTERNS):
                result.has_consent = True
                result.consent_text = text
                break

    # If there are form fields and a next/continue button, it's a form page
    if field_count > 0 and (has_next_button or has_submit_button):
        result.page_type = PageType.FORM_PAGE
        result.confidence = 0.8
        return result

    # If there are form fields, it's likely a form page
    if field_count > 0:
        result.page_type = PageType.FORM_PAGE
        result.confidence = 0.6
        return result

    # If only submit button and no other fields, likely review/submission
    if has_submit_button and not has_next_button and field_count == 0:
        result.page_type = PageType.REVIEW_PAGE
        result.confidence = 0.5
        return result

    result.page_type = PageType.UNKNOWN_PAGE
    result.confidence = 0.3
    return result


# ---------------------------------------------------------------------------
# Page identification
# ---------------------------------------------------------------------------

def identify_page(
    url: str,
    heading: str | None = None,
    step_indicator: str | None = None,
    field_labels: list[str] | None = None,
) -> PageIdentification:
    """Create a stable identification for a form page.

    Uses URL, heading, step indicator, and field signatures to create
    a unique key that survives browser refreshes.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    pathname = parsed.path.rstrip("/")

    # Build a page key from stable signals
    key_parts = [pathname]
    if heading:
        key_parts.append(heading.lower().strip())
    if step_indicator:
        key_parts.append(step_indicator.lower().strip())
    page_key = "|".join(key_parts)

    fingerprint = compute_page_fingerprint(url, heading, step_indicator, field_labels)

    return PageIdentification(
        url=url,
        pathname=pathname,
        heading=heading,
        step_indicator=step_indicator,
        page_key=page_key,
        fingerprint=fingerprint,
        field_labels=field_labels or [],
    )


# ---------------------------------------------------------------------------
# Snapshot builder
# ---------------------------------------------------------------------------

def build_page_snapshot(
    url: str,
    fields: list[DetectedField],
    navigation_elements: list[dict],
    heading: str | None = None,
    step_indicator: str | None = None,
    page_index: int = 0,
    validation_errors: list[str] | None = None,
) -> PageSnapshot:
    """Build a complete PageSnapshot from raw inspection data.

    This is the main entry point for creating page snapshots during
    the inspection phase of multi-step orchestration.
    """
    # Identify the page
    field_labels = [f.label for f in fields]
    identification = identify_page(url, heading, step_indicator, field_labels)

    # Classify the page
    nav = detect_navigation(navigation_elements)
    classification = classify_page(
        heading=heading,
        url=url,
        field_count=len(fields),
        has_submit_button=nav.has_submit,
        has_next_button=nav.has_next,
    )

    # Build tracked fields
    tracked = []
    for f in fields:
        tracked.append(TrackedField(
            detected=f,
            required=f.required,
            originally_required=f.required,
        ))

    # Count required fields
    required_count = sum(1 for t in tracked if t.required)

    snapshot = PageSnapshot(
        page_index=page_index,
        page_key=identification.page_key,
        page_type=classification.page_type,
        url=url,
        heading=heading,
        step_indicator=step_indicator or classification.step_indicator,
        fingerprint=identification.fingerprint,
        fields=tracked,
        navigation=nav.action,
        has_next_button=nav.has_next,
        has_back_button=nav.has_back,
        has_submit_button=nav.has_submit,
        has_review_button=nav.has_review,
        next_button_selector=nav.next_selector,
        back_button_selector=nav.back_selector,
        submit_button_selector=nav.submit_selector,
        validation_errors=validation_errors or [],
        required_fields_count=required_count,
    )

    return snapshot
