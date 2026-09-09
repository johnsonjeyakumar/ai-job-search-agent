"""Authentication and session state model (Phase 15).

Provides the session/authentication state machine for the application executor.
The executor must know the session_state separately from application_state,
execution_state, and queue_state. These must never be mixed.

Safety:
- Never stores passwords, OTPs, cookies, tokens, or browser secrets
- Session metadata is non-sensitive (platform, login type, timestamps)
- All detection is signal-based, not credential-based
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SessionState(str, Enum):
    """Possible authentication/session states.

    These are SEPARATE from execution statuses. The executor maps
    session states to execution actions, but they are not the same concept.
    """
    UNKNOWN = "UNKNOWN"
    AUTHENTICATED = "AUTHENTICATED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    MFA_REQUIRED = "MFA_REQUIRED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    AUTH_FAILED = "AUTH_FAILED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    BLOCKED = "BLOCKED"


class LoginType(str, Enum):
    """Type of login/authentication challenge detected."""
    PASSWORD = "PASSWORD"
    SSO_OAUTH = "SSO_OAUTH"
    MAGIC_LINK = "MAGIC_LINK"
    PASSKEY = "PASSKEY"
    SOCIAL = "SOCIAL"
    UNKNOWN = "UNKNOWN"


class MFAType(str, Enum):
    """Type of MFA/2FA challenge detected."""
    TOTP = "TOTP"
    SMS = "SMS"
    EMAIL = "EMAIL"
    PUSH = "PUSH"
    HARDWARE_KEY = "HARDWARE_KEY"
    RECOVERY_CODE = "RECOVERY_CODE"
    UNKNOWN = "UNKNOWN"


@dataclass
class AuthenticationState:
    """Result of authentication detection.

    Returned by the browser driver's detect_authentication() method.
    Contains the detected state, confidence level, evidence signals,
    and reason for the classification.
    """
    state: SessionState
    confidence: float  # 0.0 to 1.0
    evidence: list[str] = field(default_factory=list)
    detected_url: str | None = None
    reason: str = ""
    login_type: LoginType | None = None
    mfa_type: MFAType | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "detected_url": self.detected_url,
            "reason": self.reason,
            "login_type": self.login_type.value if self.login_type else None,
            "mfa_type": self.mfa_type.value if self.mfa_type else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuthenticationState:
        return cls(
            state=SessionState(data["state"]),
            confidence=data.get("confidence", 0.0),
            evidence=data.get("evidence", []),
            detected_url=data.get("detected_url"),
            reason=data.get("reason", ""),
            login_type=LoginType(data["login_type"]) if data.get("login_type") else None,
            mfa_type=MFAType(data["mfa_type"]) if data.get("mfa_type") else None,
        )

    @classmethod
    def unknown(cls, reason: str = "No reliable authentication indicators") -> AuthenticationState:
        return cls(state=SessionState.UNKNOWN, confidence=0.0, reason=reason)

    @classmethod
    def authenticated(
        cls, reason: str = "Authentication indicators present"
    ) -> AuthenticationState:
        return cls(state=SessionState.AUTHENTICATED, confidence=0.9, reason=reason)

    @classmethod
    def login_required(
        cls,
        reason: str = "Login required",
        login_type: LoginType = LoginType.UNKNOWN,
    ) -> AuthenticationState:
        return cls(
            state=SessionState.LOGIN_REQUIRED,
            confidence=0.9,
            reason=reason,
            login_type=login_type,
        )

    @classmethod
    def mfa_required(
        cls,
        reason: str = "MFA/2FA required",
        mfa_type: MFAType = MFAType.UNKNOWN,
    ) -> AuthenticationState:
        return cls(
            state=SessionState.MFA_REQUIRED,
            confidence=0.9,
            reason=reason,
            mfa_type=mfa_type,
        )

    @classmethod
    def captcha_required(cls, reason: str = "CAPTCHA detected") -> AuthenticationState:
        return cls(state=SessionState.CAPTCHA_REQUIRED, confidence=0.95, reason=reason)

    @classmethod
    def auth_failed(cls, reason: str = "Authentication failed") -> AuthenticationState:
        return cls(state=SessionState.AUTH_FAILED, confidence=0.8, reason=reason)

    @classmethod
    def session_expired(cls, reason: str = "Session expired") -> AuthenticationState:
        return cls(state=SessionState.SESSION_EXPIRED, confidence=0.85, reason=reason)

    @classmethod
    def blocked(cls, reason: str = "Blocked") -> AuthenticationState:
        return cls(state=SessionState.BLOCKED, confidence=0.9, reason=reason)


# ---------------------------------------------------------------------------
# Session state mapping to execution actions
# ---------------------------------------------------------------------------

# Which session states require human intervention
REQUIRES_HUMAN = {
    SessionState.LOGIN_REQUIRED,
    SessionState.MFA_REQUIRED,
    SessionState.CAPTCHA_REQUIRED,
    SessionState.AUTH_FAILED,
    SessionState.SESSION_EXPIRED,
}

# Which session states are terminal (cannot resume without new execution)
TERMINAL_STATES = {
    SessionState.BLOCKED,
    SessionState.AUTH_FAILED,
}

# Which session states can be resumed after human action
RESUMABLE_STATES = {
    SessionState.LOGIN_REQUIRED,
    SessionState.MFA_REQUIRED,
    SessionState.CAPTCHA_REQUIRED,
    SessionState.SESSION_EXPIRED,
}

# Maximum retry attempts for authentication detection
MAX_AUTH_DETECTION_RETRIES = 3

# Timeout for waiting for human login/MFA completion (seconds)
AUTH_WAIT_TIMEOUT_SECONDS = 300

# Interval for re-checking authentication state (seconds)
AUTH_CHECK_INTERVAL_SECONDS = 5


# ---------------------------------------------------------------------------
# Helper functions for auth state evaluation
# ---------------------------------------------------------------------------

def map_session_state_to_action(state: SessionState) -> str:
    """Map a session state to an execution action.

    Returns:
        "PROCEED" - continue execution
        "PROCEED_WITH_WARNING" - continue but log warning
        "AWAITING_USER" - wait for human login/MFA
        "BLOCKED" - cannot proceed
    """
    if state == SessionState.AUTHENTICATED:
        return "PROCEED"
    if state == SessionState.LOGIN_REQUIRED:
        return "AWAITING_USER"
    if state == SessionState.MFA_REQUIRED:
        return "AWAITING_USER"
    if state == SessionState.CAPTCHA_REQUIRED:
        return "AWAITING_USER"
    if state == SessionState.AUTH_FAILED:
        return "BLOCKED"
    if state == SessionState.SESSION_EXPIRED:
        return "BLOCKED"
    if state == SessionState.BLOCKED:
        return "BLOCKED"
    if state == SessionState.UNKNOWN:
        return "PROCEED_WITH_WARNING"
    return "PROCEED_WITH_WARNING"


def requires_human_intervention(state: SessionState) -> bool:
    """Check if a session state requires human intervention."""
    return state in REQUIRES_HUMAN


def can_auto_login(state: SessionState) -> bool:
    """Check if auto-login is possible for a session state."""
    return state not in REQUIRES_HUMAN and state not in TERMINAL_STATES


def is_auth_terminal(state: SessionState) -> bool:
    """Check if a session state is terminal."""
    return state in TERMINAL_STATES
