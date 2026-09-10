"""Browser drivers for the execution engine (Phase 7).

Safety invariants:

* no driver ever performs stealth/evasion, CAPTCHA solving, or bypasses
  authentication -- those conditions are *reported* so the executor can stop;
* passwords/cookies are never persisted by the engine (real browsers keep
  their own session state only);
* the mock driver only accepts ``mock://`` URLs so an execution against a real
  site can never be faked in tests or by mistake.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

from app.application_execution.base import (
    BrowserDriver,
    BrowserUnavailableError,
    DetectedField,
    FillResult,
    SubmissionResult,
)

_FILE_EXT_RE = re.compile(r"\.(pdf|doc|docx|txt|md|rtf)$", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Scripted scenarios used by tests and mock browse pages
# ---------------------------------------------------------------------------


def _text(key, label, required=False):
    return DetectedField(key=key, label=label, kind="text", required=required)


def _select(key, label, options, required=False):
    return DetectedField(
        key=key, label=label, kind="select", required=required, options=options
    )


def _file(key, label, required=False, accepted_types=None):
    return DetectedField(
        key=key, label=label, kind="file", required=required,
        accepted_types=accepted_types or [],
    )


def _checkbox(key, label, required=False):
    return DetectedField(key=key, label=label, kind="checkbox", required=required)


def _radio(key, label, options, required=False):
    return DetectedField(
        key=key, label=label, kind="radio", required=required, options=options
    )


def _multi_select(key, label, options, required=False):
    return DetectedField(
        key=key, label=label, kind="multi_select", required=required,
        options=options, multiple=True,
    )


def _date(key, label, required=False, pattern=None):
    return DetectedField(
        key=key, label=label, kind="date", required=required, pattern=pattern,
    )


def _currency(key, label, required=False):
    return DetectedField(key=key, label=label, kind="currency", required=required)


def _autocomplete(key, label, required=False):
    return DetectedField(key=key, label=label, kind="autocomplete", required=required)


_COMPONENT = "__resume__"
_BASE_FIELDS = [
    _text("f1", "First Name", required=True),
    _text("f2", "Last Name", required=True),
    _text("f3", "Email", required=True),
    _text("f4", "Phone"),
    _text("f5", "City"),
    _text("f6", "Country"),
    _text("f7", "Skills"),
    _select("f8", "Experience", ["0-2 years", "3-5 years"]),
    _select("f9", "Notice Period", ["Immediate", "30 days", "60 days"]),
]

SCENARIOS: dict[str, list[DetectedField]] = {
    "simple-form": list(_BASE_FIELDS),
    "dropdowns": list(_BASE_FIELDS)
    + [
        _select("d1", "Gender", ["Male", "Female", "Other"], required=True),
        _select(
            "d2",
            "Work Authorization",
            ["Authorized to work in India."],
            required=True,
        ),
        _select("d3", "Employment Type", ["Full-time", "Contract"]),
        _select("d4", "Relocation", ["Yes", "No"], required=True),
    ],
    "unknown-field": list(_BASE_FIELDS) + [_text("u1", "SSC CGPA", required=True)],
    "resume-upload": list(_BASE_FIELDS) + [_file("r1", "Upload Resume", required=True)],
    "validation-error": list(_BASE_FIELDS),
    "captcha": list(_BASE_FIELDS),
    "login-required": list(_BASE_FIELDS),
    "new-question": list(_BASE_FIELDS)
    + [_text("n1", "Why should we hire you?", required=True)],
    "confirmation": list(_BASE_FIELDS),
    "failed-submit": list(_BASE_FIELDS),
    # Phase 14: multi-page scenarios
    "multi-page": list(_BASE_FIELDS),
    "conditional": list(_BASE_FIELDS),
    "dynamic-fields": list(_BASE_FIELDS),
    "review-page": list(_BASE_FIELDS),
    # Phase 15: authentication scenarios
    "auth-authenticated": list(_BASE_FIELDS),
    "auth-password": [],  # login page, no form fields visible
    "auth-sso": [],  # SSO redirect page
    "auth-mfa": [],  # MFA/2FA prompt page
    "auth-mfa-sms": [],  # SMS verification page
    "auth-captcha": list(_BASE_FIELDS),
    "auth-failed": [],  # auth failure page
    "auth-session-expired": [],  # session expired page
    "auth-unknown": list(_BASE_FIELDS),
    # Phase 16: advanced form controls
    "advanced-checkbox": list(_BASE_FIELDS)
    + [
        _checkbox("cb1", "I agree to the Terms and Conditions", required=True),
        _checkbox("cb2", "I consent to data processing"),
        _checkbox("cb3", "Willing to relocate", required=True),
    ],
    "advanced-radio": list(_BASE_FIELDS)
    + [
        _radio("r1", "Employment Type", ["Full-time", "Part-time", "Contract", "Internship"], required=True),
        _radio("r2", "Work Preference", ["Remote", "Hybrid", "On-site"]),
        _radio("r3", "Visa Sponsorship", ["Yes", "No"], required=True),
    ],
    "advanced-multi-select": list(_BASE_FIELDS)
    + [
        _multi_select("ms1", "Skills", ["Python", "JavaScript", "React", "Node.js", "SQL", "AWS", "Docker"], required=True),
        _multi_select("ms2", "Preferred Technologies", ["TypeScript", "Go", "Rust", "Kotlin"]),
    ],
    "advanced-date": list(_BASE_FIELDS)
    + [
        _date("dt1", "Availability Date", required=True, pattern="YYYY-MM-DD"),
        _date("dt2", "Start Date"),
        _date("dt3", "Graduation Date"),
    ],
    "advanced-currency": list(_BASE_FIELDS)
    + [
        _currency("cu1", "Expected Salary", required=True),
        _currency("cu2", "Current CTC"),
    ],
    "advanced-autocomplete": list(_BASE_FIELDS)
    + [
        _autocomplete("ac1", "City", required=True),
        _autocomplete("ac2", "University"),
        _autocomplete("ac3", "Current Company"),
    ],
    "advanced-file-required": list(_BASE_FIELDS)
    + [
        _file("fr1", "Upload Resume", required=True, accepted_types=["resume"]),
    ],
    "advanced-file-optional": list(_BASE_FIELDS)
    + [
        _file("fr1", "Upload Resume", required=True, accepted_types=["resume"]),
        _file("fr2", "Cover Letter", required=False, accepted_types=["cover_letter"]),
    ],
    "advanced-file-multiple": list(_BASE_FIELDS)
    + [
        _file("fm1", "Upload Resume", required=True, accepted_types=["resume"]),
        _file("fm2", "Cover Letter", required=False, accepted_types=["cover_letter"]),
        _file("fm3", "Portfolio", required=False, accepted_types=["portfolio"]),
    ],
    "advanced-file-invalid": list(_BASE_FIELDS)
    + [
        _file("fi1", "Upload Resume", required=True, accepted_types=["resume"]),
    ],
    "advanced-file-missing": list(_BASE_FIELDS)
    + [
        _file("fm1", "Upload Resume", required=True, accepted_types=["resume"]),
    ],
    "advanced-file-ambiguous": list(_BASE_FIELDS)
    + [
        _file("fa1", "Supporting Documents", required=False, accepted_types=["resume", "cover_letter", "certificate"]),
    ],
    "advanced-mixed": list(_BASE_FIELDS)
    + [
        _checkbox("cb1", "I agree to the Terms", required=True),
        _radio("r1", "Employment Type", ["Full-time", "Part-time", "Contract"], required=True),
        _multi_select("ms1", "Skills", ["Python", "JavaScript", "React"], required=True),
        _date("dt1", "Availability Date", required=True),
        _currency("cu1", "Expected Salary", required=True),
        _autocomplete("ac1", "City", required=True),
        _file("fr1", "Upload Resume", required=True, accepted_types=["resume"]),
    ],
    "advanced-multi-page-mixed": list(_BASE_FIELDS),
}


def _scenario_for(url: str | None) -> str:
    parsed = urlparse(url or "")
    if parsed.scheme != "mock":
        return "simple-form"
    host = (parsed.hostname or "simple-form").strip("/")
    if host in SCENARIOS:
        return host
    # allow tests to combine a platform-lookalike host with any scenario via
    # the last path segment (e.g. mock://careers.acme.com/apply/validation-error)
    for segment in reversed(parsed.path.split("/")):
        if segment in SCENARIOS:
            return segment
    return "simple-form"


class MockBrowserDriver:
    """A deterministic, scripted browser used by the test suite.

    Only accepts ``mock://`` URLs. The mocked page behaves like a normal
    application form: fields can be inspected, filled and verified, the resume
    upload accepts only the approved candidate file, and submission either
    confirms, fails, or is replaced by a security challenge depending on the
    scenario behind the URL.
    """

    def __init__(self, url: str):
        parsed = urlparse(url)
        if parsed.scheme != "mock":
            raise ValueError(
                "MockBrowserDriver only accepts mock:// URLs. "
                f"Refusing to fake an execution for: {url}"
            )
        self.url = url
        self.scenario = _scenario_for(url)
        self.opened = False
        self._submitted = False
        self.filled: dict[str, str] = {}
        self.uploaded: tuple[str, str] | None = None

    # -- driver surface -----------------------------------------------------

    def open(self, url: str) -> dict:
        self.url = url
        self.opened = True
        return {"url": url, "title": f"Mock {self.scenario} application form"}

    def inspect_form(self) -> list[DetectedField]:
        return [f for f in SCENARIOS[self.scenario]]

    def fill(self, target_key: str, value: str, force_click: bool = False) -> FillResult:
        if not self.opened:
            return FillResult(status="UNKNOWN", message="Page not opened.")
        self.filled[target_key] = value
        return FillResult(key=target_key, status="KNOWN", value=value, message="Filled.")

    def upload_resume(self, data: bytes, file_name: str, content_type: str) -> FillResult:
        return self.upload_file(data, file_name, content_type, "resume")

    def upload_file(
        self, data: bytes, file_name: str, content_type: str, document_type: str = "resume",
    ) -> FillResult:
        """Upload a file to a file input field.  Validates extension and content."""
        if not self.opened:
            return FillResult(status="UNKNOWN", message="Page not opened.")
        ext_ok = bool(_FILE_EXT_RE.search(file_name or "")) or content_type == "application/pdf"
        if not data:
            return FillResult(status="UNKNOWN", message="File is empty.")
        if not ext_ok:
            return FillResult(
                status="REQUIRES_REVIEW",
                message=f"File type '{file_name}' is not an acceptable application file.",
            )
        # Simulate rejection for invalid/scenario-specific files
        if self.scenario == "advanced-file-invalid" and file_name.lower().endswith(".exe"):
            return FillResult(
                status="REQUIRES_REVIEW",
                message=f"File '{file_name}' has an invalid extension for upload.",
            )
        if self.scenario == "advanced-file-missing" and not data:
            return FillResult(
                status="UNKNOWN",
                message="No file provided for required upload.",
            )
        self.uploaded = (file_name, content_type)
        return FillResult(
            key=f"__{document_type}__",
            status="KNOWN",
            value=file_name,
            message=f"Uploaded {file_name} ({content_type}) as {document_type}.",
            control_type="file",
        )

    def get_autocomplete_suggestions(self, field_key: str, query: str) -> list[str]:
        """Return scripted autocomplete suggestions for a field."""
        _SUGGESTIONS: dict[str, list[str]] = {
            "ac1": ["San Francisco", "New York", "Seattle", "Austin", "Boston", "Chicago"],
            "ac2": ["MIT", "Stanford", "UC Berkeley", "Carnegie Mellon", "Georgia Tech"],
            "ac3": ["Google", "Microsoft", "Amazon", "Apple", "Meta", "Startup Inc"],
        }
        suggestions = _SUGGESTIONS.get(field_key, [])
        if not query:
            return suggestions
        q = query.lower()
        return [s for s in suggestions if q in s.lower()]

    def detect_captcha(self) -> bool:
        return self.scenario == "captcha"

    def detect_login(self) -> bool:
        return self.scenario in ("login-required", "auth-password", "auth-session-expired")

    def detect_authentication(self):
        """Phase 15: Multi-signal authentication detection."""
        from app.application_execution.auth import (
            AuthenticationState,
            LoginType,
            MFAType,
        )

        scenario = self.scenario

        if scenario in ("auth-authenticated",):
            return AuthenticationState.authenticated(
                reason="Account menu and logout control detected"
            )

        if scenario in ("login-required", "auth-password"):
            return AuthenticationState.login_required(
                reason="Sign-in form detected with password field",
                login_type=LoginType.PASSWORD,
            )

        if scenario == "auth-sso":
            return AuthenticationState.login_required(
                reason="SSO/OAuth redirect detected",
                login_type=LoginType.SSO_OAUTH,
            )

        if scenario == "auth-mfa":
            return AuthenticationState.mfa_required(
                reason="MFA/2FA verification prompt detected",
                mfa_type=MFAType.TOTP,
            )

        if scenario == "auth-mfa-sms":
            return AuthenticationState.mfa_required(
                reason="SMS verification code required",
                mfa_type=MFAType.SMS,
            )

        if scenario == "auth-captcha":
            return AuthenticationState.captcha_required(
                reason="CAPTCHA challenge detected"
            )

        if scenario == "auth-failed":
            return AuthenticationState.auth_failed(
                reason="Invalid credentials error detected"
            )

        if scenario in ("auth-session-expired",):
            return AuthenticationState.session_expired(
                reason="Session expired, redirect to login page"
            )

        if scenario == "auth-unknown":
            return AuthenticationState.unknown(
                reason="No reliable authentication indicators found"
            )

        # Default: assume authenticated for normal form scenarios
        return AuthenticationState.authenticated(
            reason="No login indicators detected; assuming authenticated"
        )

    def get_current_domain(self) -> str:
        """Return the current domain of the browser."""
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        return parsed.hostname or "mock.test"

    def submit(self) -> SubmissionResult:
        self._submitted = True
        if self.scenario in ("validation-error", "failed-submit"):
            return SubmissionResult(
                failure=True,
                message="Please enter your last name. (mock validation error)",
            )
        if self.scenario == "confirmation":
            return SubmissionResult(
                confirmed=True,
                reference="APP-CONFIRMED-123",
                url="https://mock.test/apply/confirmation/123",
                raw_text="Your application has been received. Application ID APP-CONFIRMED-123.",
            )
        return SubmissionResult(
            confirmed=True,
            reference="REF-" + self.scenario.upper(),
            url=f"https://mock.test/{self.scenario}/thank-you",
            raw_text=f"Thank you — application {self.scenario} accepted.",
        )

    def screenshot(self, label: str) -> str | None:
        return None  # mock driver records nothing on disk

    def close(self) -> None:
        self.opened = False

    # -- Phase 14: multi-step form support -----------------------------------

    def get_current_url(self) -> str:
        return self.url

    def get_heading(self) -> str | None:
        return f"Mock {self.scenario} application form"

    def get_navigation_elements(self) -> list[dict]:
        """Return scripted navigation elements for the scenario."""
        if self.scenario in ("multi-page", "conditional", "dynamic-fields"):
            return [
                {"selector": "button.next", "text": "Continue", "role": "button"},
            ]
        if self.scenario == "review-page":
            return [
                {"selector": "button.back", "text": "Back", "role": "button"},
                {"selector": "button.submit", "text": "Submit Application", "role": "button"},
            ]
        return []

    # -- state helper for assertions ----------------------------------------

    @property
    def submitted(self) -> bool:
        return self._submitted


class PlaywrightBrowserDriver:
    """Real-browser driver using Playwright's Python API.

    Imported lazily so the engine (and the test suite) works without Playwright
    installed. This driver only performs ordinary browser interaction --
    no stealth, no CAPTCHA solving, no authentication bypass. Authentication and
    CAPTCHA are detected so the executor can stop and hand control to the user.
    """

    def __init__(self, *, headless: bool = True, timeout_ms: int = 30000):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise BrowserUnavailableError(
                "Playwright is not installed. Install it with: "
                "pip install playwright && playwright install chromium"
            ) from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=headless)
        self._page = self._browser.new_page()
        self._page.set_default_timeout(timeout_ms)
        self._elements: dict[str, object] = {}
        self._resume_input: object | None = None

    # -- driver surface -----------------------------------------------------

    def open(self, url: str) -> dict:
        self._page.goto(url, wait_until="domcontentloaded")
        return {"url": self._page.url, "title": self._page.title()}

    def inspect_form(self) -> list[DetectedField]:
        page = self._page
        fields: list[DetectedField] = []
        for form in page.query_selector_all("form"):
            boxes = form.query_selector_all(
                "input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]), "
                "textarea, select"
            )
            submit_buttons = form.query_selector_all(
                "input[type=submit], button[type=submit]"
            )
            for box in boxes:
                label = self._label_for(box, form)
                kind = (
                    box.evaluate("(el) => el.tagName.toLowerCase()")
                    if box
                    else "text"
                )
                input_type = box.get_attribute("type") if box else None
                if kind == "input":
                    kind = (
                        "text"
                        if input_type in (None, "text", "email", "tel", "date", "number", "url")
                        else input_type
                    )
                required = bool(box.get_attribute("required"))
                options: list[str] = []
                if kind == "select":
                    options = box.evaluate(
                        "() => Array.from(this.querySelectorAll('option'))"
                        ".map(o => o.textContent.trim()).filter(Boolean)"
                    )
                elif kind == "radio":
                    group_name = box.get_attribute("name") or ""
                    if group_name and not any(
                        f.label == label and f.kind == "radio" for f in fields
                    ):
                        options = box.evaluate(
                            """(el) => {
                                const name = el.getAttribute('name');
                                if (!name) return [];
                                return Array.from(
                                    document.querySelectorAll('input[type=radio][name="' + name + '"]')
                                ).map(r => {
                                    const lbl = document.querySelector('label[for="' + r.id + '"]');
                                    return lbl ? lbl.textContent.trim() : r.value;
                                }).filter(Boolean);
                            }"""
                        )
                elif kind == "checkbox":
                    pass  # no options for checkbox
                elif kind == "number":
                    pass  # numeric input
                elif kind == "date":
                    pass  # date input
                elif kind == "url":
                    pass  # url input

                key = f"el{len(fields) + 1}-{input_type or kind}"
                fields.append(
                    DetectedField(
                        key=key,
                        label=(
                            label
                            or box.get_attribute("placeholder")
                            or box.get_attribute("name")
                            or key
                        ),
                        kind=kind,
                        required=required,
                        options=options,
                    )
                )
                self._elements[key] = box
            if not submit_buttons and not fields:
                continue
            break

        # Detect file inputs
        file_inputs = page.query_selector_all("input[type=file]")
        for fi in file_inputs:
            key = f"file-{fi.get_attribute('name') or 'upload'}"
            label = self._label_for(fi) or "File"
            accept = fi.get_attribute("accept") or ""
            fields.append(
                DetectedField(
                    key=key,
                    label=label,
                    kind="file",
                    required=bool(fi.get_attribute("required")),
                )
            )
            self._elements[key] = fi
            if self._resume_input is None:
                self._resume_input = fi
        return fields

    def _label_for(self, box, form=None) -> str:
        page = self._page
        box_id = box.get_attribute("id") if box else None
        if box_id and page.query_selector(f"label[for='{box_id}']"):
            return page.query_selector(f"label[for='{box_id}']").inner_text().strip()
        aria = box.get_attribute("aria-label") if box else None
        if aria:
            return aria.strip()
        placeholder = box.get_attribute("placeholder") if box else None
        if placeholder:
            return placeholder.strip()
        if form is not None:
            label = box.evaluate(
                "() => { const p = this.closest('label'); return p ? p.textContent.trim() : ''; }"
            )
            if label:
                return label
        name = box.get_attribute("name") if box else None
        return (name or "").strip().replace("_", " ")

    def fill(self, target_key: str, value: str) -> FillResult:
        box = self._elements.get(target_key)
        if box is None:
            return FillResult(key=target_key, status="UNKNOWN", message="Field not found.")
        try:
            tag = box.evaluate("(el) => el.tagName.toLowerCase()")
            input_type = (box.get_attribute("type") or "text").lower()

            if tag == "select":
                box.select_option(label=value)
            elif input_type == "radio":
                group_name = box.get_attribute("name")
                value_lower = value.strip().lower()
                clicked = box.evaluate(
                    """(val) => {
                        const name = this.getAttribute('name');
                        const radios = document.querySelectorAll('input[type=radio][name="' + name + '"]');
                        for (const r of radios) {
                            const lbl = document.querySelector('label[for="' + r.id + '"]');
                            const txt = (lbl ? lbl.textContent.trim() : r.value).toLowerCase();
                            if (txt === val.toLowerCase() || r.value.toLowerCase() === val.toLowerCase()) {
                                r.checked = true;
                                r.dispatchEvent(new Event('change', {bubbles: true}));
                                return true;
                            }
                        }
                        return false;
                    }""",
                    value,
                )
                if not clicked:
                    return FillResult(
                        key=target_key, status="REQUIRES_REVIEW",
                        message=f"Radio value '{value}' not found in group '{group_name}'.",
                    )
            elif input_type == "checkbox":
                should_check = value.strip().lower() in ("true", "yes", "1", "on", "checked")
                is_checked = box.is_checked()
                if should_check != is_checked:
                    box.check() if should_check else box.uncheck()
            elif input_type == "file":
                return FillResult(
                    key=target_key, status="REQUIRES_REVIEW",
                    message="Use upload_file() for file inputs.",
                )
            else:
                box.fill(value)
        except Exception as exc:  # noqa: BLE001 - driver boundary, report to executor
            return FillResult(key=target_key, status="REQUIRES_REVIEW", message=str(exc))
        return FillResult(key=target_key, status="KNOWN", value=value, message="Filled.")

    def upload_resume(self, data: bytes, file_name: str, content_type: str) -> FillResult:
        if self._resume_input is None:
            return FillResult(status="UNKNOWN", message="No file input on the page.")
        try:
            self._resume_input.set_input_files(
                files={"name": file_name, "mimeType": content_type, "buffer": data}
            )
        except Exception as exc:  # noqa: BLE001
            return FillResult(status="REQUIRES_REVIEW", message=str(exc))
        return FillResult(key="__resume__", status="KNOWN", value=file_name, message="Uploaded.")

    def upload_file(self, target_key: str, data: bytes, file_name: str, content_type: str = "application/pdf") -> FillResult:
        box = self._elements.get(target_key)
        if box is None:
            return FillResult(key=target_key, status="UNKNOWN", message="File input not found.")
        try:
            box.set_input_files(
                files={"name": file_name, "mimeType": content_type, "buffer": data}
            )
        except Exception as exc:  # noqa: BLE001
            return FillResult(key=target_key, status="REQUIRES_REVIEW", message=str(exc))
        return FillResult(key=target_key, status="KNOWN", value=file_name, message="Uploaded.")

    def click(self, target_key: str) -> FillResult:
        box = self._elements.get(target_key)
        if box is None:
            return FillResult(key=target_key, status="UNKNOWN", message="Element not found.")
        try:
            box.click()
        except Exception as exc:  # noqa: BLE001
            return FillResult(key=target_key, status="REQUIRES_REVIEW", message=str(exc))
        return FillResult(key=target_key, status="KNOWN", message="Clicked.")

    def get_text(self, selector: str = "body") -> str:
        el = self._page.query_selector(selector)
        return el.inner_text() if el else ""

    def get_attribute(self, target_key: str, attr: str) -> str | None:
        box = self._elements.get(target_key)
        if box is None:
            return None
        return box.get_attribute(attr)

    def is_checked(self, target_key: str) -> bool | None:
        box = self._elements.get(target_key)
        if box is None:
            return None
        try:
            return box.is_checked()
        except Exception:
            return None

    def get_selected_values(self, target_key: str) -> list[str]:
        box = self._elements.get(target_key)
        if box is None:
            return []
        try:
            tag = box.evaluate("(el) => el.tagName.toLowerCase()")
            if tag == "select":
                return box.evaluate(
                    "() => Array.from(this.selectedOptions).map(o => o.textContent.trim())"
                )
        except Exception:
            pass
        return []

    def detect_captcha(self) -> bool:
        page = self._page
        for sel in (
            "iframe[title*='captcha']",
            "iframe[src*='captcha']",
            "iframe[src*='recaptcha']",
        ):
            if page.query_selector(sel):
                return True
        for sel in ("input[name*='captcha']", "[class*='captcha']", "#captcha"):
            if page.query_selector(sel):
                return True
        return False

    def detect_login(self) -> bool:
        page = self._page
        for sel in ("input[type=password]", "form input[type=password]"):
            if page.query_selector(sel):
                return True
        return False

    def submit(self) -> SubmissionResult:
        page = self._page
        previous_url = page.url
        button = None
        for sel in ("button[type=submit]", "input[type=submit]", "button:has-text('Submit')"):
            button = page.query_selector(sel)
            if button:
                break
        if button is None:
            return SubmissionResult(failure=True, message="No submit control found.")
        try:
            button.click()
        except Exception as exc:  # noqa: BLE001
            return SubmissionResult(failure=True, message=str(exc))
        try:
            page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:  # noqa: BLE001 - dashboard states vary; keep going
            pass

        # Phase 19: use structured confirmation detection
        from app.application_execution.submission_verify import detect_confirmation

        text = (page.inner_text("body") or "")[:8000]
        evidence = detect_confirmation(
            page_text=text,
            current_url=page.url,
            previous_url=previous_url,
        )

        return SubmissionResult(
            confirmed=evidence.outcome.value == "SUBMISSION_CONFIRMED",
            failure=evidence.outcome.value == "SUBMISSION_FAILED",
            reference=evidence.confirmation_reference_id,
            url=page.url,
            raw_text=text[:8000],
            message=(
                evidence.failure_message
                if evidence.failure_message
                else f"Outcome: {evidence.outcome.value} "
                     f"(confidence: {evidence.confidence})."
            ),
        )

    def screenshot(self, label: str) -> str | None:
        import tempfile

        path = (
        f"{tempfile.gettempdir()}/execution_{label}_"
        f"{self._page.url[:40].replace('/', '_')}.png"
    )
        try:
            self._page.screenshot(path=path)
            return path
        except Exception:  # noqa: BLE001
            return None

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            try:
                self._playwright.stop()
            except Exception:  # noqa: BLE001 - already closed
                pass

    # -- Phase 14: multi-step form support -----------------------------------

    def get_current_url(self) -> str:
        return self._page.url

    def get_heading(self) -> str | None:
        for sel in ("h1", "h2", "[role='heading']"):
            el = self._page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text:
                    return text
        return None

    def get_navigation_elements(self) -> list[dict]:
        """Detect navigation controls on the current page."""
        elements = []
        page = self._page
        for btn in page.query_selector_all("button, a[role='button'], input[type=button]"):
            text = btn.inner_text().strip() if btn else ""
            if not text:
                text = btn.get_attribute("aria-label") or ""
            if not text:
                continue
            selector = ""
            btn_id = btn.get_attribute("id")
            if btn_id:
                selector = f"#{btn_id}"
            else:
                btn_class = btn.get_attribute("class")
                if btn_class:
                    first_class = btn_class.split()[0]
                    selector = f"button.{first_class}"
                else:
                    selector = f"button:text-is('{text}')"
            elements.append({
                "selector": selector,
                "text": text,
                "disabled": btn.get_attribute("disabled") is not None,
                "role": btn.get_attribute("role") or "button",
                "type": btn.get_attribute("type") or "button",
            })
        return elements

    # -- Phase 15: authentication detection -----------------------------------

    def detect_authentication(self):
        """Multi-signal authentication detection.

        Uses multiple signals to classify the current authentication state:
        - Password fields (login form)
        - OAuth/SSO buttons and redirects
        - MFA/2FA prompts (OTP, TOTP, SMS)
        - CAPTCHA challenges
        - Auth error messages
        - Account/logout indicators (authenticated)
        - URL patterns (login pages, auth domains)
        """

        from app.application_execution.auth import (
            AuthenticationState,
            LoginType,
            MFAType,
            SessionState,
        )

        page = self._page
        body_text = ""
        try:
            body_text = (page.inner_text("body") or "").lower()
        except Exception:  # noqa: BLE001
            pass

        current_url = page.url

        evidence = []

        # --- CAPTCHA detection ---
        if self.detect_captcha():
            return AuthenticationState.captcha_required(
                reason="CAPTCHA challenge detected"
            )

        # --- Password field detection (login form) ---
        has_password = False
        for sel in ("input[type=password]", "form input[type=password]"):
            if page.query_selector(sel):
                has_password = True
                evidence.append(f"Password field found: {sel}")
                break

        # --- MFA/2FA detection ---
        mfa_signals = [
            "enter the code", "verification code", "enter code",
            "two-factor", "2fa", "mfa", "authenticator",
            "approve sign-in", "security verification",
            "enter your otp", "one-time code",
            "we sent a code", "check your phone", "check your email",
        ]
        has_mfa_signal = any(sig in body_text for sig in mfa_signals)
        if has_mfa_signal:
            evidence.append("MFA/2FA signal text detected in body")

        # --- MFA input fields (OTP/TOTP) ---
        has_otp_input = False
        for sel in ("input[name*='otp']", "input[name*='code']", "input[name*='token']",
                     "input[autocomplete='one-time-code']", "input[inputmode='numeric']"):
            if page.query_selector(sel):
                has_otp_input = True
                evidence.append(f"OTP input field found: {sel}")
                break

        # --- OAuth/SSO detection ---
        sso_signals = [
            "sign in with", "continue with", "login with",
            "google", "linkedin", "github", "microsoft",
            "sso", "single sign-on",
        ]
        has_sso = any(sig in body_text for sig in sso_signals)
        sso_buttons = page.query_selector_all(
            "button[class*='google'], button[class*='linkedin'], "
            "button[class*='sso'], a[href*='oauth'], a[href*='sso']"
        )
        if has_sso or sso_buttons:
            evidence.append("SSO/OAuth indicators detected")

        # --- Auth error detection ---
        auth_error_signals = [
            "invalid credentials", "incorrect password", "wrong password",
            "login failed", "authentication failed", "invalid email",
            "account not found", "too many attempts", "account locked",
            "please try again", "sign in failed",
        ]
        has_auth_error = any(sig in body_text for sig in auth_error_signals)
        if has_auth_error:
            evidence.append("Authentication error message detected")

        # --- Session expired detection ---
        session_expired_signals = [
            "session expired", "session timed out", "please log in again",
            "your session has expired", "access denied", "unauthorized",
            "please sign in", "login required",
        ]
        has_session_expired = any(sig in body_text for sig in session_expired_signals)
        if has_session_expired:
            evidence.append("Session expiration signal detected")

        # --- Authenticated indicators ---
        authenticated_signals = [
            "logout", "sign out", "my account", "profile",
            "dashboard", "welcome back",
        ]
        has_auth_indicator = any(sig in body_text for sig in authenticated_signals)
        if has_auth_indicator:
            evidence.append("Authenticated user indicators detected")

        # --- URL-based signals ---
        login_url_patterns = ["/login", "/signin", "/auth", "/sso", "/oauth"]
        is_login_url = any(p in current_url.lower() for p in login_url_patterns)
        if is_login_url:
            evidence.append(f"Login URL pattern detected: {current_url}")

        # --- Classification logic ---
        # Priority: CAPTCHA > MFA > Auth Error > Session Expired
        #           > Login Required > SSO > Authenticated > Unknown

        if has_mfa_signal or has_otp_input:
            mfa_type = MFAType.UNKNOWN
            if any(s in body_text for s in ["sms", "text message", "phone"]):
                mfa_type = MFAType.SMS
            elif any(s in body_text for s in ["email", "check your inbox"]):
                mfa_type = MFAType.EMAIL
            elif any(s in body_text for s in ["authenticator app", "totp"]):
                mfa_type = MFAType.TOTP
            return AuthenticationState(
                state=SessionState.MFA_REQUIRED,
                confidence=0.9,
                evidence=evidence,
                detected_url=current_url,
                reason="MFA/2FA verification prompt detected",
                mfa_type=mfa_type,
            )

        if has_auth_error:
            return AuthenticationState(
                state=SessionState.AUTH_FAILED,
                confidence=0.85,
                evidence=evidence,
                detected_url=current_url,
                reason="Authentication error message detected",
            )

        if has_session_expired and not has_password:
            return AuthenticationState(
                state=SessionState.SESSION_EXPIRED,
                confidence=0.8,
                evidence=evidence,
                detected_url=current_url,
                reason="Session expired; re-login required",
            )

        if has_password:
            login_type = LoginType.SSO_OAUTH if has_sso else LoginType.PASSWORD
            return AuthenticationState(
                state=SessionState.LOGIN_REQUIRED,
                confidence=0.9,
                evidence=evidence,
                detected_url=current_url,
                reason="Login form with password field detected",
                login_type=login_type,
            )

        if has_sso and not has_password:
            return AuthenticationState(
                state=SessionState.LOGIN_REQUIRED,
                confidence=0.8,
                evidence=evidence,
                detected_url=current_url,
                reason="SSO/OAuth login required",
                login_type=LoginType.SSO_OAUTH,
            )

        if has_auth_indicator:
            return AuthenticationState(
                state=SessionState.AUTHENTICATED,
                confidence=0.7,
                evidence=evidence,
                detected_url=current_url,
                reason="Authenticated user indicators found",
            )

        if is_login_url:
            return AuthenticationState(
                state=SessionState.LOGIN_REQUIRED,
                confidence=0.75,
                evidence=evidence,
                detected_url=current_url,
                reason="Current URL is a login page",
            )

        # No reliable signals — default to UNKNOWN
        return AuthenticationState(
            state=SessionState.UNKNOWN,
            confidence=0.3,
            evidence=evidence,
            detected_url=current_url,
            reason="No reliable authentication indicators found",
        )

    def get_current_domain(self) -> str:
        """Return the current domain of the browser."""
        from urllib.parse import urlparse
        parsed = urlparse(self._page.url)
        return parsed.hostname or ""


def create_driver(
    url: str, driver_name: str = "auto", *, headless: bool = True
) -> BrowserDriver:
    """Build the driver for a URL.

    * ``mock``  -- only valid for ``mock://`` URLs (explicitly for tests).
    * ``playwright`` -- real browser; raises if Playwright is unavailable.
    * ``auto`` -- mock for ``mock://`` URLs, otherwise real Playwright.

    For mock:// URLs with multi-page scenarios, returns a MultiPageMockDriver
    that supports page transitions and dynamic fields.
    """
    parsed = urlparse(url or "")
    is_mock_url = parsed.scheme == "mock"
    if driver_name == "mock" and not is_mock_url:
        raise ValueError(
            "Refusing to use the mock driver outside mock:// URLs "
            "(an execution can never be faked against a real site)."
        )
    if is_mock_url:
        # Check if this is a multi-page scenario
        from tests.multi_page_mock_driver import MULTI_PAGE_SCENARIOS
        host = (parsed.hostname or "").strip("/")
        is_multi = host in MULTI_PAGE_SCENARIOS
        if not is_multi:
            for segment in reversed(parsed.path.split("/")):
                if segment in MULTI_PAGE_SCENARIOS:
                    is_multi = True
                    break
        if is_multi:
            from tests.multi_page_mock_driver import MultiPageMockDriver
            return MultiPageMockDriver(url)
        return MockBrowserDriver(url)
    if driver_name in ("auto", "playwright"):
        return PlaywrightBrowserDriver(headless=headless)
    raise BrowserUnavailableError(f"Unknown driver: {driver_name}")
