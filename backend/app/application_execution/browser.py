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


def _file(key, label, required=False):
    return DetectedField(key=key, label=label, kind="file", required=required)


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

    def fill(self, target_key: str, value: str) -> FillResult:
        if not self.opened:
            return FillResult(status="UNKNOWN", message="Page not opened.")
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
        return self.scenario == "captcha"

    def detect_login(self) -> bool:
        return self.scenario == "login-required"

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
                "input:not([type=hidden]):not([type=submit]):not([type=button]), "
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
                        if input_type in (None, "text", "email", "tel", "date")
                        else input_type
                    )
                required = bool(box.get_attribute("required"))
                options: list[str] = []
                if kind == "select":
                    options = box.evaluate(
                        "() => Array.from(document.querySelectorAll('option'))"
                        ".map(o => o.textContent.trim()).filter(Boolean)"
                    )
                key = f"el{len(fields) + 1}-{input_type or 'text'}"
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

        resumes = page.query_selector_all("input[type=file]")
        if resumes:
            key = f"resume-file-{len(resumes)}"
            self._resume_input = resumes[0]
            label = self._label_for(resumes[0])
            fields.append(
                DetectedField(key=key, label=label or "Resume", kind="file", required=True)
            )
            self._elements[key] = resumes[0]
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
            if box.evaluate("(el) => el.tagName.toLowerCase() === 'select'"):
                box.select_option(label=value)
            elif box.evaluate("(el) => el.type === 'radio' or el.type === 'checkbox'"):
                box.check()
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
        text = (page.inner_text("body") or "")[:4000]
        confirmed_markers = (
            "thank you",
            "application received",
            "application submitted",
            "application has been submitted",
            "we have received your application",
            "congratulations",
            "successfully applied",
        )
        confirmed = (
            any(m in text.lower() for m in confirmed_markers)
            or "confirmation" in page.url.lower()
        )
        return SubmissionResult(
            confirmed=confirmed,
            url=page.url,
            raw_text=text[:4000],
            message=(
                "Confirmation indicators found."
                if confirmed
                else "No confirmation marker found on the response page."
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


def create_driver(
    url: str, driver_name: str = "auto", *, headless: bool = True
) -> BrowserDriver:
    """Build the driver for a URL.

    * ``mock``  -- only valid for ``mock://`` URLs (explicitly for tests).
    * ``playwright`` -- real browser; raises if Playwright is unavailable.
    * ``auto`` -- mock for ``mock://`` URLs, otherwise real Playwright.
    """
    parsed = urlparse(url or "")
    is_mock_url = parsed.scheme == "mock"
    if driver_name == "mock" and not is_mock_url:
        raise ValueError(
            "Refusing to use the mock driver outside mock:// URLs "
            "(an execution can never be faked against a real site)."
        )
    if is_mock_url:
        return MockBrowserDriver(url)
    if driver_name in ("auto", "playwright"):
        return PlaywrightBrowserDriver(headless=headless)
    raise BrowserUnavailableError(f"Unknown driver: {driver_name}")
