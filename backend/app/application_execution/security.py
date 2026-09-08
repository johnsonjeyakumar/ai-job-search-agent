"""Security controls for application execution (Phase 26).

Enforces security policies for data handling, sensitive field protection,
and safe auto-fill behavior. Prevents accidental exposure of sensitive data
and ensures compliance with privacy requirements.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Security levels
# ---------------------------------------------------------------------------
SECURITY_PUBLIC = "PUBLIC"
SECURITY_INTERNAL = "INTERNAL"
SECURITY_CONFIDENTIAL = "CONFIDENTIAL"
SECURITY_RESTRICTED = "RESTRICTED"

# ---------------------------------------------------------------------------
# Data classification
# ---------------------------------------------------------------------------
CLASSIFICATION_PUBLIC = "PUBLIC"
CLASSIFICATION_INTERNAL = "INTERNAL"
CLASSIFICATION_CONFIDENTIAL = "CONFIDENTIAL"
CLASSIFICATION_PERSONAL = "PERSONAL"
CLASSIFICATION_FINANCIAL = "FINANCIAL"
CLASSIFICATION_AUTHORIZATION = "AUTHORIZATION"

# ---------------------------------------------------------------------------
# Field classification mapping
# ---------------------------------------------------------------------------
FIELD_CLASSIFICATION: dict[str, str] = {
    "FIRST_NAME": CLASSIFICATION_PERSONAL,
    "LAST_NAME": CLASSIFICATION_PERSONAL,
    "FULL_NAME": CLASSIFICATION_PERSONAL,
    "EMAIL": CLASSIFICATION_PERSONAL,
    "PHONE": CLASSIFICATION_PERSONAL,
    "LOCATION": CLASSIFICATION_PERSONAL,
    "STATE": CLASSIFICATION_PERSONAL,
    "COUNTRY": CLASSIFICATION_PERSONAL,
    "ADDRESS": CLASSIFICATION_PERSONAL,
    "LINKEDIN_URL": CLASSIFICATION_INTERNAL,
    "GITHUB_URL": CLASSIFICATION_INTERNAL,
    "PORTFOLIO_URL": CLASSIFICATION_INTERNAL,
    "CURRENT_COMPANY": CLASSIFICATION_CONFIDENTIAL,
    "YEARS_EXPERIENCE": CLASSIFICATION_INTERNAL,
    "CURRENT_ROLE": CLASSIFICATION_CONFIDENTIAL,
    "NOTICE_PERIOD": CLASSIFICATION_CONFIDENTIAL,
    "SALARY_EXPECTATION": CLASSIFICATION_FINANCIAL,
    "CURRENT_CTC": CLASSIFICATION_FINANCIAL,
    "DEGREE": CLASSIFICATION_PERSONAL,
    "UNIVERSITY": CLASSIFICATION_PERSONAL,
    "GRADUATION_YEAR": CLASSIFICATION_PERSONAL,
    "WORK_AUTHORIZATION": CLASSIFICATION_AUTHORIZATION,
    "SPONSORSHIP_REQUIRED": CLASSIFICATION_AUTHORIZATION,
}


@dataclass
class SecurityPolicy:
    """Security policy for application execution."""

    # Auto-fill restrictions
    auto_fill_allowed_classifications: list[str] = field(
        default_factory=lambda: [
            CLASSIFICATION_PUBLIC,
            CLASSIFICATION_INTERNAL,
            CLASSIFICATION_PERSONAL,
        ]
    )

    # Logging restrictions
    log_value_classifications: list[str] = field(
        default_factory=lambda: [CLASSIFICATION_PUBLIC]
    )

    # Storage restrictions
    store_value_classifications: list[str] = field(
        default_factory=lambda: [
            CLASSIFICATION_PUBLIC,
            CLASSIFICATION_INTERNAL,
            CLASSIFICATION_PERSONAL,
        ]
    )

    # Maximum sensitive fields per run
    max_sensitive_fields_per_run: int = 10

    # Require encryption for storage
    encrypt_storage: bool = True

    # Mask sensitive values in logs
    mask_sensitive_in_logs: bool = True


@dataclass
class SecurityCheck:
    """Result of a security check."""

    allowed: bool = True
    reason: str = ""
    classification: str = CLASSIFICATION_PUBLIC
    masked_value: str | None = None


class SecurityController:
    """Controls security for application execution."""

    def __init__(self, policy: SecurityPolicy | None = None):
        self.policy = policy or SecurityPolicy()
        self._sensitive_count = 0
        self._audit_log: list[dict] = []

    def check_auto_fill(
        self,
        canonical: str,
        value: str,
        verification_status: str,
    ) -> SecurityCheck:
        """Check if a field can be auto-filled."""
        classification = FIELD_CLASSIFICATION.get(canonical, CLASSIFICATION_PUBLIC)

        # Check classification
        if classification not in self.policy.auto_fill_allowed_classifications:
            return SecurityCheck(
                allowed=False,
                reason=(
                    f"Field '{canonical}' has classification '{classification}' "
                    f"which is not in auto-fill allowed list."
                ),
                classification=classification,
            )

        # Check sensitive field limit
        if classification in (CLASSIFICATION_FINANCIAL, CLASSIFICATION_AUTHORIZATION):
            self._sensitive_count += 1
            if self._sensitive_count > self.policy.max_sensitive_fields_per_run:
                return SecurityCheck(
                    allowed=False,
                    reason=(
                        f"Maximum sensitive fields per run "
                        f"({self.policy.max_sensitive_fields_per_run}) exceeded."
                    ),
                    classification=classification,
                )

        return SecurityCheck(
            allowed=True,
            classification=classification,
        )

    def check_logging(
        self,
        canonical: str,
        value: str,
    ) -> SecurityCheck:
        """Check if a value can be logged."""
        classification = FIELD_CLASSIFICATION.get(canonical, CLASSIFICATION_PUBLIC)

        if classification not in self.policy.log_value_classifications:
            masked = self._mask_value(value)
            return SecurityCheck(
                allowed=True,
                reason=f"Value masked for logging (classification: {classification}).",
                classification=classification,
                masked_value=masked,
            )

        return SecurityCheck(
            allowed=True,
            classification=classification,
        )

    def check_storage(
        self,
        canonical: str,
        value: str,
    ) -> SecurityCheck:
        """Check if a value can be stored."""
        classification = FIELD_CLASSIFICATION.get(canonical, CLASSIFICATION_PUBLIC)

        if classification not in self.policy.store_value_classifications:
            return SecurityCheck(
                allowed=False,
                reason=(
                    f"Field '{canonical}' has classification '{classification}' "
                    f"which is not in storage allowed list."
                ),
                classification=classification,
            )

        return SecurityCheck(
            allowed=True,
            classification=classification,
        )

    def sanitize_for_storage(self, data: dict[str, str]) -> dict[str, str]:
        """Sanitize data for storage, removing restricted fields."""
        sanitized = {}
        for key, value in data.items():
            classification = FIELD_CLASSIFICATION.get(key, CLASSIFICATION_PUBLIC)
            if classification in self.policy.store_value_classifications:
                sanitized[key] = value
        return sanitized

    def mask_value(self, value: str, canonical: str | None = None) -> str:
        """Mask a sensitive value for display."""
        if canonical:
            classification = FIELD_CLASSIFICATION.get(canonical, CLASSIFICATION_PUBLIC)
            if classification not in self.policy.log_value_classifications:
                return self._mask_value(value)
        return value

    def _mask_value(self, value: str) -> str:
        """Mask a value by showing only first and last characters."""
        if len(value) <= 2:
            return "*"
        return value[0] + "*" * (len(value) - 2) + value[-1]

    def log_audit(
        self,
        action: str,
        canonical: str,
        details: dict | None = None,
    ) -> None:
        """Log an audit entry."""
        self._audit_log.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "canonical": canonical,
            "classification": FIELD_CLASSIFICATION.get(canonical, CLASSIFICATION_PUBLIC),
            "details": details or {},
        })

    def get_audit_log(self) -> list[dict]:
        """Get the audit log."""
        return list(self._audit_log)

    def reset_sensitive_count(self) -> None:
        """Reset the sensitive field counter."""
        self._sensitive_count = 0


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_email(email: str) -> tuple[bool, str]:
    """Validate email format."""
    if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
        return False, "Invalid email format."
    return True, ""


def validate_phone(phone: str) -> tuple[bool, str]:
    """Validate phone number format."""
    cleaned = re.sub(r"[^\d+\-() ]", "", phone)
    if len(cleaned) < 7:
        return False, "Phone number too short."
    return True, ""


def validate_url(url: str) -> tuple[bool, str]:
    """Validate URL format."""
    if not url.startswith(("http://", "https://")):
        return False, "URL must start with http:// or https://."
    return True, ""


def validate_year(year: str) -> tuple[bool, str]:
    """Validate year format."""
    try:
        y = int(year)
        if y < 1900 or y > 2100:
            return False, "Year must be between 1900 and 2100."
        return True, ""
    except ValueError:
        return False, "Year must be a number."
