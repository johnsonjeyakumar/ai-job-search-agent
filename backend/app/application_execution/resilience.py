"""Idempotency and browser resilience (Phase 12).

Ensures that operations can be safely retried without side effects.
Handles browser disconnections, timeouts, and transient errors with
automatic recovery and retry logic.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Idempotency keys
# ---------------------------------------------------------------------------

def compute_idempotency_key(
    operation: str,
    run_id: str,
    field_label: str = "",
    value: str = "",
) -> str:
    """Compute an idempotency key for an operation.

    Same operation + same inputs = same key, so retrying produces
    the same result.
    """
    data = f"{operation}:{run_id}:{field_label}:{value}"
    return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class IdempotencyStore:
    """Tracks which operations have already been executed."""

    executed: dict[str, dict] = field(default_factory=dict)

    def has_executed(self, key: str) -> bool:
        """Check if an operation has already been executed."""
        return key in self.executed

    def record(self, key: str, result: dict) -> None:
        """Record that an operation was executed."""
        self.executed[key] = {
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_result(self, key: str) -> dict | None:
        """Get the result of a previously executed operation."""
        if key in self.executed:
            return self.executed[key]["result"]
        return None

    def clear(self, run_id: str | None = None) -> None:
        """Clear idempotency records."""
        if run_id:
            self.executed = {
                k: v for k, v in self.executed.items()
                if run_id not in k
            }
        else:
            self.executed.clear()


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------

@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0  # seconds
    exponential_backoff: bool = True
    retryable_errors: tuple[type[Exception], ...] = (TimeoutError, ConnectionError)


class RetryExhausted(Exception):
    """Raised when all retries are exhausted."""

    def __init__(self, last_error: Exception, attempts: int):
        self.last_error = last_error
        self.attempts = attempts
        super().__init__(
            f"Retry exhausted after {attempts} attempts. "
            f"Last error: {last_error}"
        )


def retry_with_backoff(
    func: Callable[..., Any],
    config: RetryConfig | None = None,
    *args,
    **kwargs,
) -> Any:
    """Execute a function with retry and exponential backoff.

    Args:
        func: The function to execute.
        config: Retry configuration.
        *args: Positional arguments for func.
        **kwargs: Keyword arguments for func.

    Returns:
        The result of func.

    Raises:
        RetryExhausted: If all retries fail.
    """
    config = config or RetryConfig()
    last_error = None

    for attempt in range(config.max_retries + 1):
        try:
            return func(*args, **kwargs)
        except config.retryable_errors as e:
            last_error = e
            if attempt < config.max_retries:
                delay = config.base_delay * (2 ** attempt if config.exponential_backoff else 1)
                delay = min(delay, config.max_delay)
                time.sleep(delay)

    raise RetryExhausted(last_error, config.max_retries + 1)


# ---------------------------------------------------------------------------
# Browser resilience
# ---------------------------------------------------------------------------

class BrowserResilience:
    """Handles browser disconnections and transient errors.

    Monitors browser state and attempts automatic recovery when
    the browser disconnects or becomes unresponsive.
    """

    def __init__(self, max_recovery_attempts: int = 3):
        self.max_recovery_attempts = max_recovery_attempts
        self.recovery_count = 0
        self.last_recovery_time: float | None = None
        self._is_connected = True

    @property
    def is_connected(self) -> bool:
        """Check if browser is connected."""
        return self._is_connected

    def on_disconnect(self) -> None:
        """Handle browser disconnection."""
        self._is_connected = False
        self.recovery_count += 1
        self.last_recovery_time = time.time()

    def on_reconnect(self) -> None:
        """Handle browser reconnection."""
        self._is_connected = True
        self.recovery_count = 0

    def can_recover(self) -> bool:
        """Check if recovery is possible."""
        if self.recovery_count >= self.max_recovery_attempts:
            return False

        # Reset recovery count if enough time has passed
        if self.last_recovery_time:
            elapsed = time.time() - self.last_recovery_time
            if elapsed > 60:  # 1 minute cooldown
                self.recovery_count = 0

        return True

    def wrap_operation(self, func: Callable, *args, **kwargs) -> Any:
        """Wrap an operation with resilience handling.

        If the operation fails due to browser disconnection,
        attempts to recover and retry.
        """
        if not self._is_connected:
            if not self.can_recover():
                raise ConnectionError(
                    "Browser disconnected and recovery exhausted."
                )
            # Try to recover
            self.on_reconnect()

        try:
            return func(*args, **kwargs)
        except (ConnectionError, TimeoutError):
            self.on_disconnect()
            if self.can_recover():
                # Retry once after recovery
                return func(*args, **kwargs)
            raise


# ---------------------------------------------------------------------------
# Page state validation
# ---------------------------------------------------------------------------

@dataclass
class PageState:
    """Snapshot of page state for validation."""

    url: str = ""
    title: str = ""
    field_count: int = 0
    visible_fields: list[str] = field(default_factory=list)
    has_submit_button: bool = False
    has_captcha: bool = False
    has_error_message: bool = False
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


def validate_page_state(
    expected_state: PageState,
    actual_state: PageState,
) -> tuple[bool, list[str]]:
    """Validate that the page state matches expectations.

    Returns:
        Tuple of (is_valid, list of mismatches).
    """
    mismatches = []

    # URL changed unexpectedly
    if expected_state.url and actual_state.url != expected_state.url:
        mismatches.append(
            f"URL changed: expected '{expected_state.url}', "
            f"got '{actual_state.url}'"
        )

    # Field count mismatch
    if expected_state.field_count > 0:
        if actual_state.field_count < expected_state.field_count:
            mismatches.append(
                f"Field count mismatch: expected {expected_state.field_count}, "
                f"got {actual_state.field_count}"
            )

    # Missing expected fields
    missing = set(expected_state.visible_fields) - set(actual_state.visible_fields)
    if missing:
        mismatches.append(f"Missing fields: {missing}")

    # Captcha appeared
    if actual_state.has_captcha:
        mismatches.append("CAPTCHA detected on page.")

    # Error message appeared
    if actual_state.has_error_message:
        mismatches.append("Error message detected on page.")

    return len(mismatches) == 0, mismatches
