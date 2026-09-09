"""Multi-page mock browser driver for Phase 14 integration testing.

Simulates multi-page application forms with:
- Page transitions on "Next" click
- Different fields per page
- Conditional field visibility
- Dynamic field changes
- Review pages
- Consent/declaration pages
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.application_execution.base import (
    DetectedField,
    FillResult,
    SubmissionResult,
)

_FILE_EXT_RE = re.compile(r"\.(pdf|doc|docx|txt|md|rtf)$", re.IGNORECASE)


def _text(key, label, required=False):
    return DetectedField(key=key, label=label, kind="text", required=required)


def _select(key, label, options, required=False):
    return DetectedField(
        key=key, label=label, kind="select", required=required, options=options
    )


def _file(key, label, required=False):
    return DetectedField(key=key, label=label, kind="file", required=required)


# ---------------------------------------------------------------------------
# Page definitions for multi-page scenarios
# ---------------------------------------------------------------------------

# 3-page form: Personal Info -> Education -> Review
PAGE_3_1 = {
    "heading": "Step 1 of 3: Personal Information",
    "fields": [
        _text("f1", "First Name", required=True),
        _text("f2", "Last Name", required=True),
        _text("f3", "Email", required=True),
        _text("f4", "Phone"),
    ],
    "next": True,
    "back": False,
}

PAGE_3_2 = {
    "heading": "Step 2 of 3: Education",
    "fields": [
        _text("e1", "University", required=True),
        _text("e2", "Degree", required=True),
        _text("e3", "Graduation Year"),
    ],
    "next": True,
    "back": True,
}

PAGE_3_3 = {
    "heading": "Step 3 of 3: Review & Submit",
    "fields": [
        _text("c1", "Additional Notes"),
    ],
    "next": False,
    "back": True,
    "submit": True,
}

# 5-page form
PAGE_5_1 = {
    "heading": "Step 1 of 5: Personal Information",
    "fields": [
        _text("p1", "Full Name", required=True),
        _text("p2", "Email Address", required=True),
    ],
    "next": True,
    "back": False,
}

PAGE_5_2 = {
    "heading": "Step 2 of 5: Contact Details",
    "fields": [
        _text("c1", "Phone Number", required=True),
        _text("c2", "City"),
        _text("c3", "Country"),
    ],
    "next": True,
    "back": True,
}

PAGE_5_3 = {
    "heading": "Step 3 of 5: Experience",
    "fields": [
        _select("x1", "Experience Level", ["0-2 years", "3-5 years", "5+ years"], required=True),
        _text("x2", "Current Company"),
    ],
    "next": True,
    "back": True,
}

PAGE_5_4 = {
    "heading": "Step 4 of 5: Skills",
    "fields": [
        _text("s1", "Primary Skills", required=True),
        _text("s2", "Secondary Skills"),
    ],
    "next": True,
    "back": True,
}

PAGE_5_5 = {
    "heading": "Step 5 of 5: Review Application",
    "fields": [],
    "next": False,
    "back": True,
    "submit": True,
}

# Conditional sponsorship form
PAGE_COND_1 = {
    "heading": "Step 1: Eligibility",
    "fields": [
        _select("sp1", "Work Authorization", ["Authorized", "Require Sponsorship"], required=True),
    ],
    "next": True,
    "back": False,
}

PAGE_COND_2_SPONSORED = {
    "heading": "Step 2: Sponsorship Details",
    "fields": [
        _select("sd1", "Visa Type", ["H1B", "L1", "OPT", "Other"], required=True),
        _text("sd2", "Sponsorship Timeline"),
    ],
    "next": True,
    "back": True,
}

PAGE_COND_3 = {
    "heading": "Step 3: Review & Submit",
    "fields": [],
    "next": False,
    "back": True,
    "submit": True,
}

# Dynamic field removal: field disappears after answer changes
PAGE_DYN_1 = {
    "heading": "Step 1: Employment Status",
    "fields": [
        _select("emp1", "Employment Status", ["Employed", "Unemployed", "Student"], required=True),
    ],
    "next": True,
    "back": False,
}

PAGE_DYN_2_EMPLOYED = {
    "heading": "Step 2: Current Employment",
    "fields": [
        _text("ce1", "Company Name", required=True),
        _text("ce2", "Job Title", required=True),
    ],
    "next": True,
    "back": True,
}

PAGE_DYN_2_UNEMPLOYED = {
    "heading": "Step 2: Gap Period",
    "fields": [
        _text("gp1", "Gap Duration"),
    ],
    "next": True,
    "back": True,
}

PAGE_DYN_3 = {
    "heading": "Step 3: Review",
    "fields": [],
    "next": False,
    "back": True,
    "submit": True,
}

# Review page scenario
PAGE_REVIEW_1 = {
    "heading": "Application Form",
    "fields": [
        _text("r1", "Full Name", required=True),
        _text("r2", "Email", required=True),
    ],
    "next": True,
    "back": False,
}

PAGE_REVIEW_2 = {
    "heading": "Review Your Application",
    "fields": [],
    "next": False,
    "back": True,
    "submit": True,
    "is_review": True,
}

# 3-page form with resume upload
PAGE_RESUME_1 = {
    "heading": "Step 1: Personal Information",
    "fields": [
        _text("f1", "First Name", required=True),
        _text("f2", "Last Name", required=True),
    ],
    "next": True,
    "back": False,
}

PAGE_RESUME_2 = {
    "heading": "Step 2: Upload Resume",
    "fields": [
        _file("r1", "Upload Resume", required=True),
    ],
    "next": True,
    "back": True,
}

PAGE_RESUME_3 = {
    "heading": "Step 3: Review & Submit",
    "fields": [],
    "next": False,
    "back": True,
    "submit": True,
}

# Scenario page maps
MULTI_PAGE_SCENARIOS = {
    "3page": [PAGE_3_1, PAGE_3_2, PAGE_3_3],
    "5page": [PAGE_5_1, PAGE_5_2, PAGE_5_3, PAGE_5_4, PAGE_5_5],
    "conditional": [PAGE_COND_1, PAGE_COND_2_SPONSORED, PAGE_COND_3],
    "dynamic-removal": [PAGE_DYN_1, PAGE_DYN_2_EMPLOYED, PAGE_DYN_3],
    "review-page": [PAGE_REVIEW_1, PAGE_REVIEW_2],
}


class MultiPageMockDriver:
    """Mock browser driver that simulates multi-page application forms.

    Supports page transitions, conditional fields, dynamic field changes,
    and review pages. Only accepts mock:// URLs.
    """

    def __init__(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme != "mock":
            raise ValueError(
                "MultiPageMockDriver only accepts mock:// URLs. "
                f"Refusing to fake an execution for: {url}"
            )
        self.url = url
        self.scenario = self._resolve_scenario(url)
        self.pages = MULTI_PAGE_SCENARIOS.get(self.scenario, [])
        self.current_page_idx = 0
        self.opened = False
        self._submitted = False
        self.filled: dict[str, str] = {}
        self.uploaded: tuple[str, str] | None = None
        self.page_urls: list[str] = [url]
        self._page_field_cache: dict[int, list[DetectedField]] = {}

    def _resolve_scenario(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip("/")
        if host in MULTI_PAGE_SCENARIOS:
            return host
        for segment in reversed(parsed.path.split("/")):
            if segment in MULTI_PAGE_SCENARIOS:
                return segment
        return "3page"  # default

    def _current_page(self) -> dict:
        if self.current_page_idx < len(self.pages):
            return self.pages[self.current_page_idx]
        return self.pages[-1] if self.pages else {}

    def open(self, url: str) -> dict:
        self.url = url
        self.opened = True
        self.current_page_idx = 0
        page = self._current_page()
        return {"url": url, "title": page.get("heading", "Mock form")}

    def inspect_form(self) -> list[DetectedField]:
        page = self._current_page()
        fields = list(page.get("fields", []))
        self._page_field_cache[self.current_page_idx] = fields
        return fields

    def fill(self, target_key: str, value: str, force_click: bool = False) -> FillResult:
        if not self.opened:
            return FillResult(status="UNKNOWN", message="Page not opened.")
        # If force_click and target is a navigation button, handle page transition
        if force_click:
            page = self._current_page()
            if page.get("next") and target_key in ("button.next", "next", ".next"):
                if self.current_page_idx < len(self.pages) - 1:
                    self.current_page_idx += 1
                    self.page_urls.append(self.url)
                    return FillResult(
                        key=target_key, status="KNOWN", value="navigated",
                        message="Navigated to next page."
                    )
            if page.get("submit") and target_key in ("button.submit", "submit", ".submit"):
                self._submitted = True
                return FillResult(
                    key=target_key, status="KNOWN", value="submitted",
                    message="Form submitted."
                )
        self.filled[target_key] = value
        return FillResult(key=target_key, status="KNOWN", value=value, message="Filled.")

    def upload_resume(self, data: bytes, file_name: str, content_type: str) -> FillResult:
        if not self.opened:
            return FillResult(status="UNKNOWN", message="Page not opened.")
        ext_ok = bool(_FILE_EXT_RE.search(file_name or "")) or content_type == "application/pdf"
        if not data:
            return FillResult(status="UNKNOWN", message="Resume file is empty.")
        if not ext_ok:
            return FillResult(
                status="REQUIRES_REVIEW",
                message=f"Resume type '{file_name}' is not an acceptable application file.",
            )
        self.uploaded = (file_name, content_type)
        return FillResult(
            key="__resume__",
            status="KNOWN",
            value=file_name,
            message=f"Uploaded {file_name} ({content_type}).",
        )

    def detect_captcha(self) -> bool:
        return False

    def detect_login(self) -> bool:
        return False

    def detect_authentication(self):
        """Phase 15: Multi-signal authentication detection."""
        from app.application_execution.auth import AuthenticationState
        # Multi-page mock forms are always authenticated
        return AuthenticationState.authenticated(
            reason="Multi-page mock form; no login required"
        )

    def get_current_domain(self) -> str:
        """Return the current domain."""
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        return parsed.hostname or "mock.test"

    def submit(self) -> SubmissionResult:
        self._submitted = True
        return SubmissionResult(
            confirmed=True,
            reference="REF-MULTIPAGE",
            url="https://mock.test/multi-page/thank-you",
            raw_text="Thank you — application accepted.",
        )

    def screenshot(self, label: str) -> str | None:
        return None

    def close(self) -> None:
        self.opened = False

    def get_current_url(self) -> str:
        return self.url

    def get_heading(self) -> str | None:
        page = self._current_page()
        return page.get("heading")

    def get_navigation_elements(self) -> list[dict]:
        page = self._current_page()
        nav = []
        if page.get("back"):
            nav.append({"selector": "button.back", "text": "Back", "role": "button"})
        if page.get("next"):
            nav.append({"selector": "button.next", "text": "Continue", "role": "button"})
        if page.get("submit"):
            nav.append({"selector": "button.submit", "text": "Submit Application", "role": "button"})
        return nav

    @property
    def submitted(self) -> bool:
        return self._submitted

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def current_page_index(self) -> int:
        return self.current_page_idx
