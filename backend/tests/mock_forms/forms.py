"""Mock form suite for Phase 14 multi-step testing (Forms A-M).

Each form is defined as a sequence of pages with fields, navigation,
and behavior rules. The forms are served as local HTML for Playwright E2E
testing, or used via the MockBrowserDriver for unit testing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.application_execution.base import DetectedField

# ---------------------------------------------------------------------------
# Page definition
# ---------------------------------------------------------------------------

@dataclass
class MockPage:
    """A single page in a mock form."""
    page_key: str
    heading: str
    url: str
    fields: list[DetectedField] = field(default_factory=list)
    navigation: list[dict] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)
    is_review: bool = False
    is_submission: bool = False
    consent_text: str | None = None
    conditional_fields: dict[str, list[DetectedField]] = field(default_factory=dict)


@dataclass
class MockForm:
    """A complete multi-page mock form."""
    form_id: str
    name: str
    pages: list[MockPage] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _text(key: str, label: str, required: bool = False) -> DetectedField:
    return DetectedField(key=key, label=label, kind="text", required=required)


def _select(key: str, label: str, options: list[str], required: bool = False) -> DetectedField:
    return DetectedField(key=key, label=label, kind="select", required=required, options=options)


def _radio(key: str, label: str, options: list[str], required: bool = False) -> DetectedField:
    return DetectedField(key=key, label=label, kind="radio", required=required, options=options)


def _checkbox(key: str, label: str, required: bool = False) -> DetectedField:
    return DetectedField(key=key, label=label, kind="checkbox", required=required)


def _next_button() -> dict:
    return {"selector": "button.next", "text": "Continue", "role": "button"}


def _back_button() -> dict:
    return {"selector": "button.back", "text": "Back", "role": "button"}


def _submit_button() -> dict:
    return {"selector": "button.submit", "text": "Submit Application", "role": "button"}


# ---------------------------------------------------------------------------
# FORM A: Single-page application
# ---------------------------------------------------------------------------

FORM_A = MockForm(
    form_id="form-a",
    name="Single-page application",
    pages=[
        MockPage(
            page_key="form-a-basic",
            heading="Basic Information",
            url="https://mock.test/apply/form-a",
            fields=[
                _text("first_name", "First Name", required=True),
                _text("last_name", "Last Name", required=True),
                _text("email", "Email Address", required=True),
                _text("phone", "Phone Number"),
                _text("location", "City"),
            ],
            navigation=[_submit_button()],
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM B: 3-page application
# ---------------------------------------------------------------------------

FORM_B = MockForm(
    form_id="form-b",
    name="3-page application",
    pages=[
        MockPage(
            page_key="form-b-basic",
            heading="Basic Information",
            url="https://mock.test/apply/form-b/1",
            fields=[
                _text("first_name", "First Name", required=True),
                _text("last_name", "Last Name", required=True),
                _text("email", "Email", required=True),
            ],
            navigation=[_next_button()],
        ),
        MockPage(
            page_key="form-b-experience",
            heading="Experience",
            url="https://mock.test/apply/form-b/2",
            fields=[
                _text("company", "Current Company", required=True),
                _text("role", "Current Role", required=True),
                _text("years", "Years of Experience", required=True),
            ],
            navigation=[_back_button(), _next_button()],
        ),
        MockPage(
            page_key="form-b-review",
            heading="Review Your Application",
            url="https://mock.test/apply/form-b/3",
            fields=[],
            navigation=[_back_button(), _submit_button()],
            is_review=True,
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM C: 5-page application
# ---------------------------------------------------------------------------

FORM_C = MockForm(
    form_id="form-c",
    name="5-page application",
    pages=[
        MockPage(
            page_key="form-c-p1",
            heading="Personal Information",
            url="https://mock.test/apply/form-c/1",
            fields=[
                _text("first_name", "First Name", required=True),
                _text("last_name", "Last Name", required=True),
            ],
            navigation=[_next_button()],
        ),
        MockPage(
            page_key="form-c-p2",
            heading="Contact Details",
            url="https://mock.test/apply/form-c/2",
            fields=[
                _text("email", "Email", required=True),
                _text("phone", "Phone"),
            ],
            navigation=[_back_button(), _next_button()],
        ),
        MockPage(
            page_key="form-c-p3",
            heading="Work Experience",
            url="https://mock.test/apply/form-c/3",
            fields=[
                _text("company", "Current Company", required=True),
                _text("role", "Current Role", required=True),
            ],
            navigation=[_back_button(), _next_button()],
        ),
        MockPage(
            page_key="form-c-p4",
            heading="Education",
            url="https://mock.test/apply/form-c/4",
            fields=[
                _text("university", "University", required=True),
                _text("degree", "Degree"),
            ],
            navigation=[_back_button(), _next_button()],
        ),
        MockPage(
            page_key="form-c-p5",
            heading="Review & Submit",
            url="https://mock.test/apply/form-c/5",
            fields=[],
            navigation=[_back_button(), _submit_button()],
            is_review=True,
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM D: Conditional sponsorship question
# ---------------------------------------------------------------------------

FORM_D = MockForm(
    form_id="form-d",
    name="Conditional sponsorship",
    pages=[
        MockPage(
            page_key="form-d-main",
            heading="Application Questions",
            url="https://mock.test/apply/form-d",
            fields=[
                _text("first_name", "First Name", required=True),
                _text("last_name", "Last Name", required=True),
                _select("sponsorship", "Do you require visa sponsorship?", ["Yes", "No"], required=True),
            ],
            navigation=[_submit_button()],
            conditional_fields={
                "Yes": [
                    _select("sponsorship_type", "What type of sponsorship?", ["H-1B", "L-1", "OPT", "Other"], required=True),
                    _text("sponsorship_notes", "Additional details about your sponsorship needs"),
                ],
            },
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM E: Conditional experience question
# ---------------------------------------------------------------------------

FORM_E = MockForm(
    form_id="form-e",
    name="Conditional experience",
    pages=[
        MockPage(
            page_key="form-e-main",
            heading="Technical Skills",
            url="https://mock.test/apply/form-e",
            fields=[
                _select("has_docker", "Do you have experience with Docker?", ["Yes", "No"], required=True),
            ],
            navigation=[_submit_button()],
            conditional_fields={
                "Yes": [
                    _text("docker_years", "Years of Docker experience", required=True),
                ],
            },
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM F: Dynamic fields appear after selection
# ---------------------------------------------------------------------------

FORM_F = MockForm(
    form_id="form-f",
    name="Dynamic fields appear",
    pages=[
        MockPage(
            page_key="form-f-main",
            heading="Relocation & Preferences",
            url="https://mock.test/apply/form-f",
            fields=[
                _radio("relocation", "Are you willing to relocate?", ["Yes", "No"], required=True),
            ],
            navigation=[_submit_button()],
            conditional_fields={
                "Yes": [
                    _select("preferred_locations", "Preferred locations", ["SF", "NYC", "Austin", "Seattle", "Remote"], required=True),
                ],
            },
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM G: Dynamic fields disappear
# ---------------------------------------------------------------------------

FORM_G = MockForm(
    form_id="form-g",
    name="Dynamic fields disappear",
    pages=[
        MockPage(
            page_key="form-g-main",
            heading="Availability",
            url="https://mock.test/apply/form-g",
            fields=[
                _select("employment_type", "Employment type", ["Full-time", "Part-time", "Contract"], required=True),
                _text("hours_per_week", "Hours per week"),
            ],
            navigation=[_submit_button()],
            # When "Full-time" is selected, hours_per_week becomes irrelevant
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM H: Review page
# ---------------------------------------------------------------------------

FORM_H = MockForm(
    form_id="form-h",
    name="Review page",
    pages=[
        MockPage(
            page_key="form-h-form",
            heading="Application Form",
            url="https://mock.test/apply/form-h/1",
            fields=[
                _text("first_name", "First Name", required=True),
                _text("last_name", "Last Name", required=True),
                _text("email", "Email", required=True),
            ],
            navigation=[_next_button()],
        ),
        MockPage(
            page_key="form-h-review",
            heading="Review Your Application",
            url="https://mock.test/apply/form-h/2",
            fields=[],
            navigation=[_back_button(), _submit_button()],
            is_review=True,
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM I: Final consent/declaration
# ---------------------------------------------------------------------------

FORM_I = MockForm(
    form_id="form-i",
    name="Consent/declaration",
    pages=[
        MockPage(
            page_key="form-i-form",
            heading="Application Form",
            url="https://mock.test/apply/form-i/1",
            fields=[
                _text("first_name", "First Name", required=True),
                _text("last_name", "Last Name", required=True),
            ],
            navigation=[_next_button()],
        ),
        MockPage(
            page_key="form-i-declare",
            heading="Declaration",
            url="https://mock.test/apply/form-i/2",
            fields=[
                _checkbox("agree_terms", "I certify that the information provided is accurate and complete.", required=True),
            ],
            navigation=[_back_button(), _submit_button()],
            consent_text="I certify that the information provided is accurate and complete.",
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM J: Navigation timeout
# ---------------------------------------------------------------------------

FORM_J = MockForm(
    form_id="form-j",
    name="Navigation timeout",
    pages=[
        MockPage(
            page_key="form-j-main",
            heading="Slow Form",
            url="https://mock.test/apply/form-j",
            fields=[
                _text("name", "Name", required=True),
            ],
            navigation=[_next_button()],
            # This form simulates a timeout: next button exists but navigation fails
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM K: Page reload
# ---------------------------------------------------------------------------

FORM_K = MockForm(
    form_id="form-k",
    name="Page reload",
    pages=[
        MockPage(
            page_key="form-k-main",
            heading="Reload Form",
            url="https://mock.test/apply/form-k",
            fields=[
                _text("name", "Name", required=True),
                _text("email", "Email", required=True),
            ],
            navigation=[_submit_button()],
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM L: Interrupted execution
# ---------------------------------------------------------------------------

FORM_L = MockForm(
    form_id="form-l",
    name="Interrupted execution",
    pages=[
        MockPage(
            page_key="form-l-p1",
            heading="Step 1",
            url="https://mock.test/apply/form-l/1",
            fields=[_text("name", "Name", required=True)],
            navigation=[_next_button()],
        ),
        MockPage(
            page_key="form-l-p2",
            heading="Step 2",
            url="https://mock.test/apply/form-l/2",
            fields=[_text("email", "Email", required=True)],
            navigation=[_next_button()],
        ),
        MockPage(
            page_key="form-l-p3",
            heading="Step 3",
            url="https://mock.test/apply/form-l/3",
            fields=[_text("phone", "Phone", required=True)],
            navigation=[_submit_button()],
        ),
    ],
)

# ---------------------------------------------------------------------------
# FORM M: Already submitted
# ---------------------------------------------------------------------------

FORM_M = MockForm(
    form_id="form-m",
    name="Already submitted",
    pages=[
        MockPage(
            page_key="form-m-main",
            heading="Application Submitted",
            url="https://mock.test/apply/form-m/thank-you",
            fields=[],
            navigation=[],
            is_submission=True,
        ),
    ],
)

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

MOCK_FORMS: dict[str, MockForm] = {
    "form-a": FORM_A,
    "form-b": FORM_B,
    "form-c": FORM_C,
    "form-d": FORM_D,
    "form-e": FORM_E,
    "form-f": FORM_F,
    "form-g": FORM_G,
    "form-h": FORM_H,
    "form-i": FORM_I,
    "form-j": FORM_J,
    "form-k": FORM_K,
    "form-l": FORM_L,
    "form-m": FORM_M,
}


def get_mock_form(form_id: str) -> MockForm | None:
    return MOCK_FORMS.get(form_id)
