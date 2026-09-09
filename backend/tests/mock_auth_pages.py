"""Mock authentication pages for Phase 15 testing.

Provides mock browser drivers with different authentication states
for comprehensive testing of the authentication detection system.
"""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.application_execution.auth import (
    AuthenticationState,
    LoginType,
    MFAType,
    SessionState,
)
from app.application_execution.base import FillResult


@dataclass
class MockAuthPage:
    """Represents a mock page with specific authentication state."""
    name: str
    url: str
    auth_state: SessionState
    body_text: str = ""
    has_password_field: bool = False
    has_otp_input: bool = False
    has_captcha: bool = False
    has_sso_button: bool = False
    has_account_menu: bool = False
    login_type: LoginType | None = None
    mfa_type: MFAType | None = None


# Pre-built auth scenarios
MOCK_AUTH_PAGES: dict[str, MockAuthPage] = {
    "authenticated": MockAuthPage(
        name="authenticated",
        url="https://jobs.lever.co/applicants/123",
        auth_state=SessionState.AUTHENTICATED,
        body_text="Welcome back, John! Logout | My Account | Dashboard",
        has_account_menu=True,
    ),
    "login-required": MockAuthPage(
        name="login-required",
        url="https://jobs.lever.co/login",
        auth_state=SessionState.LOGIN_REQUIRED,
        body_text="Sign in to your account. Don't have an account? Register.",
        has_password_field=True,
        login_type=LoginType.PASSWORD,
    ),
    "sso-required": MockAuthPage(
        name="sso-required",
        url="https://jobs.lever.co/sso/redirect",
        auth_state=SessionState.LOGIN_REQUIRED,
        body_text="Sign in with Google | Continue with LinkedIn | Single sign-on",
        has_sso_button=True,
        login_type=LoginType.SSO_OAUTH,
    ),
    "mfa-totp": MockAuthPage(
        name="mfa-totp",
        url="https://jobs.lever.co/mfa/verify",
        auth_state=SessionState.MFA_REQUIRED,
        body_text="Enter the code from your authenticator app. Two-factor authentication.",
        has_otp_input=True,
        mfa_type=MFAType.TOTP,
    ),
    "mfa-sms": MockAuthPage(
        name="mfa-sms",
        url="https://jobs.lever.co/mfa/sms",
        auth_state=SessionState.MFA_REQUIRED,
        body_text="We sent a code to your phone via SMS. Check your text messages.",
        has_otp_input=True,
        mfa_type=MFAType.SMS,
    ),
    "mfa-email": MockAuthPage(
        name="mfa-email",
        url="https://jobs.lever.co/mfa/email",
        auth_state=SessionState.MFA_REQUIRED,
        body_text="Enter the verification code we sent to your email. Check your inbox.",
        has_otp_input=True,
        mfa_type=MFAType.EMAIL,
    ),
    "captcha": MockAuthPage(
        name="captcha",
        url="https://jobs.lever.co/apply/123",
        auth_state=SessionState.CAPTCHA_REQUIRED,
        body_text="Please complete the CAPTCHA challenge to continue.",
        has_captcha=True,
    ),
    "auth-failed": MockAuthPage(
        name="auth-failed",
        url="https://jobs.lever.co/login",
        auth_state=SessionState.AUTH_FAILED,
        body_text="Invalid credentials. Incorrect password. Please try again.",
        has_password_field=True,
    ),
    "session-expired": MockAuthPage(
        name="session-expired",
        url="https://jobs.lever.co/apply/123",
        auth_state=SessionState.SESSION_EXPIRED,
        body_text="Your session has expired. Please log in again. Access denied.",
    ),
    "unknown": MockAuthPage(
        name="unknown",
        url="https://jobs.lever.co/apply/123",
        auth_state=SessionState.UNKNOWN,
        body_text="Application form - no login indicators.",
    ),
}


class MockAuthBrowserDriver:
    """Mock browser driver with controllable authentication states.

    Used for testing the authentication detection system without
    needing a real browser.
    """

    def __init__(self, auth_page: MockAuthPage):
        self.auth_page = auth_page
        self.url = auth_page.url
        self.opened = True
        self._submitted = False

    def open(self, url: str) -> dict:
        self.url = url
        self.opened = True
        return {"url": url, "title": f"Mock - {self.auth_page.name}"}

    def inspect_form(self) -> list:
        """Return fields based on the auth state."""
        from app.application_execution.detector import DetectedField
        fields = []
        if self.auth_page.has_password_field:
            fields.append(DetectedField(
                key="email",
                kind="text",
                label="Email",
                required=True,
            ))
            fields.append(DetectedField(
                key="password",
                kind="text",
                label="Password",
                required=True,
            ))
        if self.auth_page.has_otp_input:
            fields.append(DetectedField(
                key="otp",
                kind="text",
                label="Verification Code",
                required=True,
            ))
        return fields

    def fill(self, target_key: str, value: str, *, force_click: bool = False) -> FillResult:
        return FillResult(key=target_key, status="KNOWN", value=value, message="Filled.")

    def detect_captcha(self) -> bool:
        return self.auth_page.has_captcha

    def detect_login(self) -> bool:
        return self.auth_page.has_password_field

    def detect_authentication(self) -> AuthenticationState:
        """Return the configured authentication state."""
        evidence = []
        if self.auth_page.has_password_field:
            evidence.append("Password field detected")
        if self.auth_page.has_otp_input:
            evidence.append("OTP input field detected")
        if self.auth_page.has_captcha:
            evidence.append("CAPTCHA challenge detected")
        if self.auth_page.has_sso_button:
            evidence.append("SSO button detected")
        if self.auth_page.has_account_menu:
            evidence.append("Account menu detected")
        if self.auth_page.body_text:
            evidence.append(f"Body text: {self.auth_page.body_text[:100]}")

        return AuthenticationState(
            state=self.auth_page.auth_state,
            confidence=0.9 if self.auth_page.auth_state != SessionState.UNKNOWN else 0.3,
            evidence=evidence,
            detected_url=self.url,
            reason=f"Mock auth page: {self.auth_page.name}",
            login_type=self.auth_page.login_type,
            mfa_type=self.auth_page.mfa_type,
        )

    def get_current_domain(self) -> str:
        parsed = urlparse(self.url)
        return parsed.hostname or "mock.test"

    def get_current_url(self) -> str:
        return self.url

    def get_heading(self) -> str | None:
        return None

    def get_navigation_elements(self) -> list[dict]:
        return []

    def upload_resume(self, data: bytes, file_name: str, content_type: str) -> FillResult:
        return FillResult(key="__resume__", status="KNOWN", value=file_name, message="Uploaded.")

    def submit(self):
        from app.application_execution.base import SubmissionResult
        self._submitted = True
        return SubmissionResult(
            confirmed=True,
            reference="MOCK-AUTH-123",
            url=self.url,
            raw_text="Application submitted.",
        )

    def screenshot(self, label: str) -> str | None:
        return None

    def close(self) -> None:
        self.opened = False
