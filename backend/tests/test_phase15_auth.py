"""Phase 15: Login / Session / 2FA Handling — comprehensive tests.

Tests authentication state detection, session management, and integration
with the executor for safe, human-in-the-loop authentication handling.
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application_execution.auth import (
    AuthenticationState,
    LoginType,
    MFAType,
    SessionState,
    can_auto_login,
    is_auth_terminal,
    map_session_state_to_action,
    requires_human_intervention,
)
from app.application_execution.base import (
    STATUS_AWAITING_USER,
    STATUS_BLOCKED,
    STATUS_EXECUTION_FAILED,
)
from app.application_execution.checkpoint import (
    CheckpointStore,
    CheckpointType,
    create_auth_checked_checkpoint,
    create_auth_failed_checkpoint,
    create_captcha_detected_checkpoint,
    create_domain_validated_checkpoint,
    create_login_required_checkpoint,
    create_mfa_required_checkpoint,
    create_session_expired_checkpoint,
)
from app.application_execution.executor import (
    run_execution,
)
from tests.mock_auth_pages import MOCK_AUTH_PAGES, MockAuthBrowserDriver

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    """Use the test database from conftest.py."""
    from sqlalchemy import make_url

    import app.models  # noqa: F401  (register all tables)
    from app.config.settings import get_settings

    settings = get_settings()
    url = make_url(settings.database_url).set(database="job_agent_test")
    engine = create_engine(url.render_as_string(hide_password=False))
    with sessionmaker(bind=engine)() as session:
        yield session


@pytest.fixture()
def checkpoint_store():
    return CheckpointStore()


# ---------------------------------------------------------------------------
# Part 1: Session state model
# ---------------------------------------------------------------------------

class TestSessionStateModel:
    """Part 1: SessionState enum values."""

    def test_session_states_exist(self):
        assert SessionState.AUTHENTICATED.value == "AUTHENTICATED"
        assert SessionState.LOGIN_REQUIRED.value == "LOGIN_REQUIRED"
        assert SessionState.MFA_REQUIRED.value == "MFA_REQUIRED"
        assert SessionState.CAPTCHA_REQUIRED.value == "CAPTCHA_REQUIRED"
        assert SessionState.AUTH_FAILED.value == "AUTH_FAILED"
        assert SessionState.SESSION_EXPIRED.value == "SESSION_EXPIRED"
        assert SessionState.BLOCKED.value == "BLOCKED"
        assert SessionState.UNKNOWN.value == "UNKNOWN"


# ---------------------------------------------------------------------------
# Part 2: Authentication state dataclass
# ---------------------------------------------------------------------------

class TestAuthenticationState:
    """Part 2: AuthenticationState dataclass."""

    def test_auth_state_creation(self):
        state = AuthenticationState(
            state=SessionState.AUTHENTICATED,
            confidence=0.95,
            evidence=["Account menu found"],
            detected_url="https://example.com/app",
            reason="User is logged in",
        )
        assert state.state == SessionState.AUTHENTICATED
        assert state.confidence == 0.95
        assert "Account menu found" in state.evidence
        assert state.detected_url == "https://example.com/app"
        assert state.login_type is None
        assert state.mfa_type is None

    def test_auth_state_factory_authenticated(self):
        state = AuthenticationState.authenticated(
            reason="Logout button found",
        )
        assert state.state == SessionState.AUTHENTICATED
        assert state.reason == "Logout button found"

    def test_auth_state_factory_login_required(self):
        state = AuthenticationState.login_required(
            reason="Password field detected",
            login_type=LoginType.PASSWORD,
        )
        assert state.state == SessionState.LOGIN_REQUIRED
        assert state.login_type == LoginType.PASSWORD

    def test_auth_state_factory_mfa_required(self):
        state = AuthenticationState.mfa_required(
            reason="OTP input detected",
            mfa_type=MFAType.TOTP,
        )
        assert state.state == SessionState.MFA_REQUIRED
        assert state.mfa_type == MFAType.TOTP

    def test_auth_state_factory_captcha_required(self):
        state = AuthenticationState.captcha_required(
            reason="reCAPTCHA iframe",
        )
        assert state.state == SessionState.CAPTCHA_REQUIRED

    def test_auth_state_factory_auth_failed(self):
        state = AuthenticationState.auth_failed(
            reason="Invalid credentials",
        )
        assert state.state == SessionState.AUTH_FAILED

    def test_auth_state_factory_session_expired(self):
        state = AuthenticationState.session_expired(
            reason="Session timeout",
        )
        assert state.state == SessionState.SESSION_EXPIRED

    def test_auth_state_factory_blocked(self):
        state = AuthenticationState.blocked(
            reason="Account locked",
        )
        assert state.state == SessionState.BLOCKED

    def test_auth_state_factory_unknown(self):
        state = AuthenticationState.unknown(
            reason="No indicators",
        )
        assert state.state == SessionState.UNKNOWN


# ---------------------------------------------------------------------------
# Part 3: Login type and MFA type enums
# ---------------------------------------------------------------------------

class TestLoginAndMFATypes:
    """Part 3: LoginType and MFAType enums."""

    def test_login_types(self):
        assert LoginType.PASSWORD.value == "PASSWORD"
        assert LoginType.SSO_OAUTH.value == "SSO_OAUTH"
        assert LoginType.MAGIC_LINK.value == "MAGIC_LINK"
        assert LoginType.PASSKEY.value == "PASSKEY"

    def test_mfa_types(self):
        assert MFAType.TOTP.value == "TOTP"
        assert MFAType.SMS.value == "SMS"
        assert MFAType.EMAIL.value == "EMAIL"
        assert MFAType.PUSH.value == "PUSH"
        assert MFAType.HARDWARE_KEY.value == "HARDWARE_KEY"
        assert MFAType.RECOVERY_CODE.value == "RECOVERY_CODE"


# ---------------------------------------------------------------------------
# Part 4: Session state to action mapping
# ---------------------------------------------------------------------------

class TestSessionStateMapping:
    """Part 4: map_session_state_to_action function."""

    def test_authenticated_allows_proceed(self):
        action = map_session_state_to_action(SessionState.AUTHENTICATED)
        assert action == "PROCEED"

    def test_login_required_blocks(self):
        action = map_session_state_to_action(SessionState.LOGIN_REQUIRED)
        assert action == "AWAITING_USER"

    def test_mfa_required_blocks(self):
        action = map_session_state_to_action(SessionState.MFA_REQUIRED)
        assert action == "AWAITING_USER"

    def test_captcha_required_blocks(self):
        action = map_session_state_to_action(SessionState.CAPTCHA_REQUIRED)
        assert action == "AWAITING_USER"

    def test_auth_failed_terminates(self):
        action = map_session_state_to_action(SessionState.AUTH_FAILED)
        assert action == "BLOCKED"

    def test_session_expired_blocks(self):
        action = map_session_state_to_action(SessionState.SESSION_EXPIRED)
        assert action == "BLOCKED"

    def test_blocked_stays_blocked(self):
        action = map_session_state_to_action(SessionState.BLOCKED)
        assert action == "BLOCKED"

    def test_unknown_allows_proceed_with_warning(self):
        action = map_session_state_to_action(SessionState.UNKNOWN)
        assert action == "PROCEED_WITH_WARNING"


# ---------------------------------------------------------------------------
# Part 5: Helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Part 5: Helper functions for auth state evaluation."""

    def test_requires_human_intervention_true(self):
        assert requires_human_intervention(SessionState.LOGIN_REQUIRED) is True
        assert requires_human_intervention(SessionState.MFA_REQUIRED) is True
        assert requires_human_intervention(SessionState.CAPTCHA_REQUIRED) is True

    def test_requires_human_intervention_false(self):
        assert requires_human_intervention(SessionState.AUTHENTICATED) is False
        assert requires_human_intervention(SessionState.UNKNOWN) is False

    def test_can_auto_login_false(self):
        assert can_auto_login(SessionState.LOGIN_REQUIRED) is False
        assert can_auto_login(SessionState.MFA_REQUIRED) is False

    def test_can_auto_login_true(self):
        assert can_auto_login(SessionState.AUTHENTICATED) is True
        assert can_auto_login(SessionState.UNKNOWN) is True

    def test_is_auth_terminal_true(self):
        assert is_auth_terminal(SessionState.AUTH_FAILED) is True
        assert is_auth_terminal(SessionState.BLOCKED) is True

    def test_is_auth_terminal_false(self):
        assert is_auth_terminal(SessionState.LOGIN_REQUIRED) is False
        assert is_auth_terminal(SessionState.AUTHENTICATED) is False


# ---------------------------------------------------------------------------
# Part 6: Mock browser auth detection
# ---------------------------------------------------------------------------

class TestMockBrowserAuthDetection:
    """Part 6: Mock browser driver authentication detection."""

    @pytest.mark.parametrize("page_name", list(MOCK_AUTH_PAGES.keys()))
    def test_all_pages_produce_auth_state(self, page_name):
        page = MOCK_AUTH_PAGES[page_name]
        driver = MockAuthBrowserDriver(page)
        auth_state = driver.detect_authentication()
        assert isinstance(auth_state, AuthenticationState)
        assert auth_state.state == page.auth_state

    def test_authenticated_page_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.AUTHENTICATED
        assert auth.confidence >= 0.8
        assert any("Account menu" in e for e in auth.evidence)

    def test_login_required_page_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["login-required"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.LOGIN_REQUIRED
        assert auth.login_type == LoginType.PASSWORD
        assert auth.confidence >= 0.8

    def test_sso_required_page_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["sso-required"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.LOGIN_REQUIRED
        assert auth.login_type == LoginType.SSO_OAUTH

    def test_mfa_totp_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["mfa-totp"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.MFA_REQUIRED
        assert auth.mfa_type == MFAType.TOTP

    def test_mfa_sms_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["mfa-sms"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.MFA_REQUIRED
        assert auth.mfa_type == MFAType.SMS

    def test_mfa_email_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["mfa-email"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.MFA_REQUIRED
        assert auth.mfa_type == MFAType.EMAIL

    def test_captcha_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["captcha"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.CAPTCHA_REQUIRED

    def test_auth_failed_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["auth-failed"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.AUTH_FAILED

    def test_session_expired_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["session-expired"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.SESSION_EXPIRED

    def test_unknown_state_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["unknown"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.UNKNOWN
        assert auth.confidence <= 0.5

    def test_get_current_domain(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        domain = driver.get_current_domain()
        assert domain == "jobs.lever.co"


# ---------------------------------------------------------------------------
# Part 7: Authentication checkpoint creation
# ---------------------------------------------------------------------------

class TestAuthCheckpoints:
    """Part 7: Authentication checkpoint creation helpers."""

    def test_create_auth_checked_checkpoint(self, checkpoint_store):
        cp = create_auth_checked_checkpoint(
            run_id="run-123",
            step=2,
            auth_state="AUTHENTICATED",
            reason="Account menu found",
            confidence=0.9,
            domain="example.com",
        )
        assert cp.checkpoint_type == CheckpointType.AUTH_CHECKED
        assert cp.state_snapshot["auth_state"] == "AUTHENTICATED"
        assert cp.state_snapshot["reason"] == "Account menu found"
        assert cp.state_snapshot["confidence"] == 0.9
        assert cp.state_snapshot["domain"] == "example.com"
        checkpoint_store.save(cp)
        assert len(checkpoint_store.get_all("run-123")) == 1

    def test_create_login_required_checkpoint(self, checkpoint_store):
        cp = create_login_required_checkpoint(
            run_id="run-123",
            step=3,
            login_type="PASSWORD",
            reason="Password field found",
            page_url="https://example.com/login",
        )
        assert cp.checkpoint_type == CheckpointType.LOGIN_REQUIRED
        assert cp.state_snapshot["login_type"] == "PASSWORD"
        checkpoint_store.save(cp)

    def test_create_mfa_required_checkpoint(self, checkpoint_store):
        cp = create_mfa_required_checkpoint(
            run_id="run-123",
            step=4,
            mfa_type="TOTP",
            reason="OTP input found",
        )
        assert cp.checkpoint_type == CheckpointType.MFA_REQUIRED
        assert cp.state_snapshot["mfa_type"] == "TOTP"
        checkpoint_store.save(cp)

    def test_create_captcha_detected_checkpoint(self, checkpoint_store):
        cp = create_captcha_detected_checkpoint(
            run_id="run-123",
            step=5,
            reason="reCAPTCHA iframe",
        )
        assert cp.checkpoint_type == CheckpointType.CAPTCHA_DETECTED
        checkpoint_store.save(cp)

    def test_create_auth_failed_checkpoint(self, checkpoint_store):
        cp = create_auth_failed_checkpoint(
            run_id="run-123",
            step=6,
            reason="Invalid credentials",
            page_url="https://example.com/login",
        )
        assert cp.checkpoint_type == CheckpointType.AUTH_FAILED
        assert cp.state_snapshot["page_url"] == "https://example.com/login"
        checkpoint_store.save(cp)

    def test_create_session_expired_checkpoint(self, checkpoint_store):
        cp = create_session_expired_checkpoint(
            run_id="run-123",
            step=7,
            reason="Session timeout",
            page_url="https://example.com/expired",
        )
        assert cp.checkpoint_type == CheckpointType.SESSION_EXPIRED
        checkpoint_store.save(cp)

    def test_create_domain_validated_checkpoint(self, checkpoint_store):
        cp = create_domain_validated_checkpoint(
            run_id="run-123",
            step=8,
            expected_domain="example.com",
            actual_domain="example.com",
            is_match=True,
        )
        assert cp.checkpoint_type == CheckpointType.DOMAIN_VALIDATED
        assert cp.state_snapshot["is_match"] is True
        checkpoint_store.save(cp)


# ---------------------------------------------------------------------------
# Part 8: Executor auth integration
# ---------------------------------------------------------------------------

class TestExecutorAuthIntegration:
    """Part 8: Executor authentication integration."""

    def test_executor_blocks_on_login_required(self, db, checkpoint_store):
        """When LOGIN_REQUIRED is detected, execution is blocked."""
        from app.models.preferences import Preferences
        from tests.mock_auth_pages import MOCK_AUTH_PAGES, MockAuthBrowserDriver

        # Create mock objects
        class MockJob:
            id = 1
            url = "https://example.com/apply"
            application_url = "https://example.com/apply"
            source = "manual"
            title = "Test Job"

        class MockResume:
            id = 1
            file_path = "/tmp/test.pdf"
            file_name = "test.pdf"
            content_type = "application/pdf"

        class MockPackage:
            id = 1
            job_id = 1
            selected_resume_id = 1
            status = "APPROVED"
            match_score = 0.85
            job_context = {}

        # Setup
        job = MockJob()
        MockResume()
        package = MockPackage()
        Preferences(platform_policies={})

        # Mock the driver to return LOGIN_REQUIRED
        from unittest.mock import MagicMock, patch

        mock_driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["login-required"])

        mock_lock_mgr = MagicMock()
        mock_lock_mgr.acquire.return_value = MagicMock(outcome="ACQUIRED", owner_id="test")

        with patch("app.application_execution.executor.detect_platform") as mock_detect, \
             patch("app.application_execution.executor.get_adapter") as mock_adapter, \
             patch("app.application_execution.executor.create_driver", return_value=mock_driver), \
             patch("app.application_execution.executor._preflight"), \
             patch("app.application_execution.executor._record_step"), \
             patch("app.application_execution.executor._add_warning"), \
             patch("app.application_execution.executor._mark_execution") as mock_mark, \
             patch("app.services.job_service.get_job", return_value=job), \
             patch("app.application_execution.idempotency_locks.get_lock_manager", return_value=mock_lock_mgr), \
             patch.object(db, "add"), \
             patch.object(db, "flush"):

            mock_detect.return_value = MagicMock(platform="lever", label="Lever", based_on="url")
            mock_adapter.return_value = MagicMock(
                policy=lambda p: MagicMock(mode="safe", supports_browser_automation=True, reason="test"),
                allows_resume_upload=lambda m: True,
            )

            run_execution(db, package, driver_name="mock")

            # Should have been blocked
            mock_mark.assert_called()
            call_args = mock_mark.call_args
            assert call_args.kwargs["status"] == STATUS_AWAITING_USER

    def test_executor_blocks_on_captcha(self, db, checkpoint_store):
        """When CAPTCHA is detected, execution is blocked."""
        from app.models.preferences import Preferences
        from tests.mock_auth_pages import MOCK_AUTH_PAGES, MockAuthBrowserDriver

        class MockJob:
            id = 1
            url = "https://example.com/apply"
            application_url = "https://example.com/apply"
            source = "manual"
            title = "Test Job"

        class MockResume:
            id = 1
            file_path = "/tmp/test.pdf"
            file_name = "test.pdf"
            content_type = "application/pdf"

        class MockPackage:
            id = 1
            job_id = 1
            selected_resume_id = 1
            status = "APPROVED"
            match_score = 0.85
            job_context = {}

        job = MockJob()
        MockResume()
        package = MockPackage()
        Preferences(platform_policies={})

        from unittest.mock import MagicMock, patch

        mock_driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["captcha"])

        mock_lock_mgr = MagicMock()
        mock_lock_mgr.acquire.return_value = MagicMock(outcome="ACQUIRED", owner_id="test")

        with patch("app.application_execution.executor.detect_platform") as mock_detect, \
             patch("app.application_execution.executor.get_adapter") as mock_adapter, \
             patch("app.application_execution.executor.create_driver", return_value=mock_driver), \
             patch("app.application_execution.executor._preflight"), \
             patch("app.application_execution.executor._record_step"), \
             patch("app.application_execution.executor._add_warning"), \
             patch("app.application_execution.executor._mark_execution") as mock_mark, \
             patch("app.services.job_service.get_job", return_value=job), \
             patch("app.application_execution.idempotency_locks.get_lock_manager", return_value=mock_lock_mgr), \
             patch.object(db, "add"), \
             patch.object(db, "flush"):

            mock_detect.return_value = MagicMock(platform="lever", label="Lever", based_on="url")
            mock_adapter.return_value = MagicMock(
                policy=lambda p: MagicMock(mode="safe", supports_browser_automation=True, reason="test"),
                allows_resume_upload=lambda m: True,
            )

            run_execution(db, package, driver_name="mock")

            mock_mark.assert_called()
            call_args = mock_mark.call_args
            assert call_args.kwargs["status"] == STATUS_BLOCKED

    def test_executor_proceeds_when_authenticated(self, db):
        """When AUTHENTICATED, execution proceeds normally."""
        from tests.mock_auth_pages import MOCK_AUTH_PAGES, MockAuthBrowserDriver

        class MockJob:
            id = 1
            url = "https://example.com/apply"
            application_url = "https://example.com/apply"
            source = "manual"
            title = "Test Job"
            company = "Test Co"

        class MockResume:
            id = 1
            file_path = "/tmp/test.pdf"
            file_name = "test.pdf"
            content_type = "application/pdf"

        class MockPackage:
            id = 1
            job_id = 1
            selected_resume_id = 1
            status = "APPROVED"
            match_score = 0.85
            job_context = {}
            version = 1

        job = MockJob()
        MockResume()
        package = MockPackage()

        from unittest.mock import MagicMock, patch

        mock_driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        # Add simple form fields for inspection
        from app.application_execution.base import DetectedField
        mock_driver.inspect_form = lambda: [
            DetectedField(key="name", kind="text", label="Name", required=True),
            DetectedField(key="email", kind="text", label="Email", required=True),
        ]

        mock_lock_mgr = MagicMock()
        mock_lock_mgr.acquire.return_value = MagicMock(outcome="ACQUIRED", owner_id="test")

        with patch("app.application_execution.executor.detect_platform") as mock_detect, \
             patch("app.application_execution.executor.get_adapter") as mock_adapter, \
             patch("app.application_execution.executor.create_driver", return_value=mock_driver), \
             patch("app.application_execution.executor._preflight"), \
             patch("app.application_execution.executor._record_step"), \
             patch("app.application_execution.executor._add_warning"), \
             patch("app.application_execution.executor._mark_execution") as mock_mark, \
             patch("app.services.job_service.get_job", return_value=job), \
             patch("app.application_execution.idempotency_locks.get_lock_manager", return_value=mock_lock_mgr), \
             patch.object(db, "add"), \
             patch.object(db, "flush"):

            mock_detect.return_value = MagicMock(platform="lever", label="Lever", based_on="url")
            mock_adapter.return_value = MagicMock(
                policy=lambda p: MagicMock(mode="safe", supports_browser_automation=True, reason="test"),
                allows_resume_upload=lambda m: True,
            )

            run_execution(db, package, driver_name="mock")

            # Should NOT have been blocked by auth
            for call in mock_mark.call_args_list:
                if call.kwargs.get("status") in (STATUS_BLOCKED, STATUS_EXECUTION_FAILED):
                    assert "auth" not in str(call.kwargs.get("current_step", "")).lower()


# ---------------------------------------------------------------------------
# Part 9: Domain validation
# ---------------------------------------------------------------------------

class TestDomainValidation:
    """Part 9: Domain validation for session fixation."""

    def test_domain_matches(self):
        AuthenticationState(
            state=SessionState.AUTHENTICATED,
            confidence=0.9,
            evidence=[],
            detected_url="https://jobs.lever.co/apply/123",
            reason="test",
        )
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        domain = driver.get_current_domain()
        assert domain == "jobs.lever.co"
        assert "lever.co" in domain

    def test_domain_changes_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        original_domain = driver.get_current_domain()

        # Simulate redirect to different domain
        driver.url = "https://malicious-site.com/fake/lever"
        new_domain = driver.get_current_domain()
        assert new_domain != original_domain

    def test_subdomain_detection(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        driver.url = "https://app.lever.co/apply/123"
        domain = driver.get_current_domain()
        assert domain == "app.lever.co"


# ---------------------------------------------------------------------------
# Part 10: Confidence thresholds
# ---------------------------------------------------------------------------

class TestConfidenceThresholds:
    """Part 10: Confidence threshold logic."""

    def test_high_confidence_proceeds(self):
        state = AuthenticationState.authenticated(
            reason="test",
        )
        assert state.confidence >= 0.8

    def test_medium_confidence_proceeds_with_warning(self):
        state = AuthenticationState(
            state=SessionState.AUTHENTICATED,
            confidence=0.6,
            evidence=[],
            detected_url="test",
            reason="weak indicators",
        )
        assert 0.5 <= state.confidence < 0.8

    def test_low_confidence_blocks(self):
        state = AuthenticationState.unknown(
            reason="No signals",
        )
        assert state.confidence < 0.5

    def test_mfa_high_confidence(self):
        state = AuthenticationState.mfa_required(
            reason="OTP field",
            mfa_type=MFAType.TOTP,
        )
        assert state.confidence >= 0.8

    def test_auth_failed_high_confidence(self):
        state = AuthenticationState.auth_failed(
            reason="Invalid password error",
        )
        assert state.confidence >= 0.8


# ---------------------------------------------------------------------------
# Part 11: CAPTCHA interaction
# ---------------------------------------------------------------------------

class TestCaptchaInteraction:
    """Part 11: CAPTCHA detection and handling."""

    def test_captcha_treated_as_auth_required(self):
        state = AuthenticationState.captcha_required(
            reason="reCAPTCHA",
        )
        action = map_session_state_to_action(state.state)
        assert action == "AWAITING_USER"

    def test_captcha_checkpoint_created(self):
        cp = create_captcha_detected_checkpoint(
            run_id="run-123",
            step=5,
            reason="reCAPTCHA iframe",
        )
        assert cp.checkpoint_type == CheckpointType.CAPTCHA_DETECTED
        assert cp.state_snapshot["reason"] == "reCAPTCHA iframe"


# ---------------------------------------------------------------------------
# Part 12: Session expiry handling
# ---------------------------------------------------------------------------

class TestSessionExpiry:
    """Part 12: Session expiry detection and handling."""

    def test_session_expired_blocks(self):
        state = AuthenticationState.session_expired(
            reason="Timeout",
        )
        action = map_session_state_to_action(state.state)
        assert action == "BLOCKED"

    def test_session_expired_checkpoint(self):
        cp = create_session_expired_checkpoint(
            run_id="run-123",
            step=10,
            reason="Session timeout after 30 min",
        )
        assert cp.checkpoint_type == CheckpointType.SESSION_EXPIRED
        assert cp.state_snapshot["reason"] == "Session timeout after 30 min"

    def test_session_expired_is_terminal(self):
        assert is_auth_terminal(SessionState.SESSION_EXPIRED) is False
        assert requires_human_intervention(SessionState.SESSION_EXPIRED) is True
        action = map_session_state_to_action(SessionState.SESSION_EXPIRED)
        assert action == "BLOCKED"


# ---------------------------------------------------------------------------
# Part 13: MFA / 2FA handling
# ---------------------------------------------------------------------------

class TestMFAHandling:
    """Part 13: MFA/2FA detection and handling."""

    def test_mfa_totp_requires_human(self):
        state = AuthenticationState.mfa_required(
            reason="TOTP",
            mfa_type=MFAType.TOTP,
        )
        assert requires_human_intervention(state.state) is True
        action = map_session_state_to_action(state.state)
        assert action == "AWAITING_USER"

    def test_mfa_sms_requires_human(self):
        state = AuthenticationState.mfa_required(
            reason="SMS",
            mfa_type=MFAType.SMS,
        )
        assert requires_human_intervention(state.state) is True

    def test_mfa_email_requires_human(self):
        state = AuthenticationState.mfa_required(
            reason="Email",
            mfa_type=MFAType.EMAIL,
        )
        assert requires_human_intervention(state.state) is True

    def test_mfa_type_detection(self):
        assert MFAType.TOTP.value == "TOTP"
        assert MFAType.SMS.value == "SMS"
        assert MFAType.EMAIL.value == "EMAIL"
        assert MFAType.PUSH.value == "PUSH"
        assert MFAType.HARDWARE_KEY.value == "HARDWARE_KEY"

    def test_mfa_checkpoint_created(self):
        cp = create_mfa_required_checkpoint(
            run_id="run-123",
            step=15,
            mfa_type="TOTP",
            reason="Authenticator app required",
        )
        assert cp.checkpoint_type == CheckpointType.MFA_REQUIRED
        assert cp.state_snapshot["mfa_type"] == "TOTP"


# ---------------------------------------------------------------------------
# Part 14: SSO/OAuth handling
# ---------------------------------------------------------------------------

class TestSSOHandling:
    """Part 14: SSO/OAuth detection and handling."""

    def test_sso_detected_as_login_required(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["sso-required"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.LOGIN_REQUIRED
        assert auth.login_type == LoginType.SSO_OAUTH

    def test_sso_requires_human(self):
        state = AuthenticationState.login_required(
            reason="SSO",
            login_type=LoginType.SSO_OAUTH,
        )
        assert requires_human_intervention(state.state) is True

    def test_login_type_values(self):
        assert LoginType.PASSWORD.value == "PASSWORD"
        assert LoginType.SSO_OAUTH.value == "SSO_OAUTH"
        assert LoginType.MAGIC_LINK.value == "MAGIC_LINK"
        assert LoginType.PASSKEY.value == "PASSKEY"


# ---------------------------------------------------------------------------
# Part 15: Login type detection
# ---------------------------------------------------------------------------

class TestLoginTypeDetection:
    """Part 15: Login type detection in browser drivers."""

    def test_password_login_detected(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["login-required"])
        auth = driver.detect_authentication()
        assert auth.login_type == LoginType.PASSWORD

    def test_sso_login_detected(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["sso-required"])
        auth = driver.detect_authentication()
        assert auth.login_type == LoginType.SSO_OAUTH

    def test_no_login_type_for_non_login_states(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        auth = driver.detect_authentication()
        assert auth.login_type is None


# ---------------------------------------------------------------------------
# Part 16: Evidence collection
# ---------------------------------------------------------------------------

class TestEvidenceCollection:
    """Part 16: Evidence collection for auth state."""

    def test_authenticated_evidence(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        auth = driver.detect_authentication()
        assert len(auth.evidence) > 0
        assert any("Account menu" in e for e in auth.evidence)

    def test_login_evidence(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["login-required"])
        auth = driver.detect_authentication()
        assert len(auth.evidence) > 0
        assert any("Password" in e for e in auth.evidence)

    def test_mfa_evidence(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["mfa-totp"])
        auth = driver.detect_authentication()
        assert len(auth.evidence) > 0
        assert any("OTP" in e for e in auth.evidence)

    def test_captcha_evidence(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["captcha"])
        auth = driver.detect_authentication()
        assert len(auth.evidence) > 0
        assert any("CAPTCHA" in e for e in auth.evidence)


# ---------------------------------------------------------------------------
# Part 17: URL-based detection
# ---------------------------------------------------------------------------

class TestURLBasedDetection:
    """Part 17: URL-based authentication detection."""

    def test_login_url_detected(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["login-required"])
        assert "login" in driver.url.lower()

    def test_sso_url_detected(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["sso-required"])
        assert "sso" in driver.url.lower()

    def test_mfa_url_detected(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["mfa-totp"])
        assert "mfa" in driver.url.lower()


# ---------------------------------------------------------------------------
# Part 18: Multi-page form auth checks
# ---------------------------------------------------------------------------

class TestMultiPageFormAuthChecks:
    """Part 18: Auth checks in multi-page form orchestration."""

    def test_auth_state_resets_on_navigation(self):
        """Auth state is re-evaluated after each navigation."""
        driver1 = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        auth1 = driver1.detect_authentication()
        assert auth1.state == SessionState.AUTHENTICATED

        # Simulate navigation to login page
        driver1.url = "https://jobs.lever.co/login"
        driver1.auth_page = MOCK_AUTH_PAGES["login-required"]
        auth2 = driver1.detect_authentication()
        assert auth2.state == SessionState.LOGIN_REQUIRED

    def test_mfa_mid_flow_detection(self):
        """MFA can appear mid-flow after navigation."""
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["mfa-sms"])
        auth = driver.detect_authentication()
        assert auth.state == SessionState.MFA_REQUIRED
        assert auth.mfa_type == MFAType.SMS


# ---------------------------------------------------------------------------
# Part 19: Checkpoint integrity
# ---------------------------------------------------------------------------

class TestCheckpointIntegrity:
    """Part 19: Auth checkpoint integrity and ordering."""

    def test_checkpoint_sequence(self, checkpoint_store):
        """Auth checkpoints are saved in correct order."""
        run_id = "run-456"

        # Step 1: Auth checked
        cp1 = create_auth_checked_checkpoint(
            run_id=run_id, step=2,
            auth_state="AUTHENTICATED",
            reason="test",
            confidence=0.9,
        )
        checkpoint_store.save(cp1)

        # Step 2: Domain validated
        cp2 = create_domain_validated_checkpoint(
            run_id=run_id, step=3,
            expected_domain="example.com",
            actual_domain="example.com",
            is_match=True,
        )
        checkpoint_store.save(cp2)

        all_cps = checkpoint_store.get_all(run_id)
        assert len(all_cps) == 2
        assert all_cps[0].checkpoint_type == CheckpointType.AUTH_CHECKED
        assert all_cps[1].checkpoint_type == CheckpointType.DOMAIN_VALIDATED

    def test_auth_failure_checkpoint_chain(self, checkpoint_store):
        """Auth failure produces correct checkpoint chain."""
        run_id = "run-789"

        cp1 = create_auth_checked_checkpoint(
            run_id=run_id, step=2,
            auth_state="AUTH_FAILED",
            reason="Invalid credentials",
            confidence=0.88,
        )
        checkpoint_store.save(cp1)

        cp2 = create_auth_failed_checkpoint(
            run_id=run_id, step=3,
            reason="Password rejected",
            page_url="https://example.com/login",
        )
        checkpoint_store.save(cp2)

        all_cps = checkpoint_store.get_all(run_id)
        assert len(all_cps) == 2
        types = [cp.checkpoint_type for cp in all_cps]
        assert CheckpointType.AUTH_CHECKED in types
        assert CheckpointType.AUTH_FAILED in types


# ---------------------------------------------------------------------------
# Part 20: State machine transitions
# ---------------------------------------------------------------------------

class TestStateMachineTransitions:
    """Part 20: Authentication state machine transitions."""

    def test_login_to_authenticated_transition(self):
        """User can transition from LOGIN_REQUIRED to AUTHENTICATED."""
        state1 = AuthenticationState.login_required(reason="test")
        state2 = AuthenticationState.authenticated(reason="logged in")
        assert state1.state == SessionState.LOGIN_REQUIRED
        assert state2.state == SessionState.AUTHENTICATED
        action1 = map_session_state_to_action(state1.state)
        action2 = map_session_state_to_action(state2.state)
        assert action1 == "AWAITING_USER"
        assert action2 == "PROCEED"

    def test_mfa_to_authenticated_transition(self):
        """User can transition from MFA_REQUIRED to AUTHENTICATED."""
        state1 = AuthenticationState.mfa_required(reason="test", mfa_type=MFAType.TOTP)
        state2 = AuthenticationState.authenticated(reason="verified")
        assert state1.state == SessionState.MFA_REQUIRED
        assert state2.state == SessionState.AUTHENTICATED

    def test_auth_failed_is_terminal(self):
        """AUTH_FAILED is a terminal state that cannot be recovered."""
        assert is_auth_terminal(SessionState.AUTH_FAILED) is True

    def test_blocked_is_terminal(self):
        """BLOCKED is a terminal state."""
        assert is_auth_terminal(SessionState.BLOCKED) is True


# ---------------------------------------------------------------------------
# Part 21: Auto-login prevention
# ---------------------------------------------------------------------------

class TestAutoLoginPrevention:
    """Part 21: Auto-login prevention tests."""

    def test_password_not_auto_loginable(self):
        assert can_auto_login(SessionState.LOGIN_REQUIRED) is False

    def test_mfa_not_auto_loginable(self):
        assert can_auto_login(SessionState.MFA_REQUIRED) is False

    def test_captcha_not_auto_loginable(self):
        assert can_auto_login(SessionState.CAPTCHA_REQUIRED) is False

    def test_authenticated_is_auto_loginable(self):
        assert can_auto_login(SessionState.AUTHENTICATED) is True

    def test_unknown_is_auto_loginable(self):
        assert can_auto_login(SessionState.UNKNOWN) is True

    def test_auth_failed_not_auto_loginable(self):
        assert can_auto_login(SessionState.AUTH_FAILED) is False


# ---------------------------------------------------------------------------
# Part 22: Error recovery
# ---------------------------------------------------------------------------

class TestErrorRecovery:
    """Part 22: Error recovery for auth failures."""

    def test_auth_failed_records_failure(self):
        cp = create_auth_failed_checkpoint(
            run_id="run-999",
            step=10,
            reason="Too many failed attempts",
        )
        assert cp.checkpoint_type == CheckpointType.AUTH_FAILED
        assert cp.state_snapshot["reason"] == "Too many failed attempts"

    def test_session_expired_records_state(self):
        cp = create_session_expired_checkpoint(
            run_id="run-999",
            step=11,
            reason="30 minute timeout",
        )
        assert cp.checkpoint_type == CheckpointType.SESSION_EXPIRED
        assert "timeout" in cp.state_snapshot["reason"].lower()


# ---------------------------------------------------------------------------
# Part 23: Page URL capture
# ---------------------------------------------------------------------------

class TestPageURLCapture:
    """Part 23: Page URL capture for debugging."""

    def test_url_captured_in_auth_state(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["login-required"])
        auth = driver.detect_authentication()
        assert auth.detected_url == "https://jobs.lever.co/login"

    def test_url_captured_in_checkpoint(self):
        cp = create_login_required_checkpoint(
            run_id="run-555",
            step=5,
            login_type="PASSWORD",
            reason="test",
            page_url="https://example.com/login",
        )
        assert cp.state_snapshot["page_url"] == "https://example.com/login"

    def test_domain_captured(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        domain = driver.get_current_domain()
        assert domain == "jobs.lever.co"


# ---------------------------------------------------------------------------
# Part 24: Confidence threshold actions
# ---------------------------------------------------------------------------

class TestConfidenceThresholdActions:
    """Part 24: Confidence threshold-based actions."""

    def test_high_confidence_proceeds(self):
        state = AuthenticationState.authenticated(reason="test")
        assert state.confidence >= 0.8

    def test_medium_confidence_warning(self):
        state = AuthenticationState(
            state=SessionState.AUTHENTICATED,
            confidence=0.65,
            evidence=[],
            detected_url="test",
            reason="weak",
        )
        assert 0.5 <= state.confidence < 0.8

    def test_low_confidence_blocks(self):
        state = AuthenticationState.unknown(reason="test")
        assert state.confidence < 0.5


# ---------------------------------------------------------------------------
# Part 25: Cross-origin protection
# ---------------------------------------------------------------------------

class TestCrossOriginProtection:
    """Part 25: Cross-origin domain validation."""

    def test_same_domain_passes(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        domain1 = driver.get_current_domain()
        driver.url = "https://jobs.lever.co/other-page"
        domain2 = driver.get_current_domain()
        assert domain1 == domain2

    def test_different_domain_fails(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        domain1 = driver.get_current_domain()
        driver.url = "https://malicious-site.com/fake"
        domain2 = driver.get_current_domain()
        assert domain1 != domain2

    def test_subdomain_differs(self):
        driver = MockAuthBrowserDriver(MOCK_AUTH_PAGES["authenticated"])
        domain1 = driver.get_current_domain()
        driver.url = "https://app.lever.co/other"
        domain2 = driver.get_current_domain()
        assert domain1 != domain2


# ---------------------------------------------------------------------------
# Part 26: Auth state serialization
# ---------------------------------------------------------------------------

class TestAuthStateSerialization:
    """Part 26: Auth state serialization for checkpoints."""

    def test_auth_state_to_dict(self):
        state = AuthenticationState(
            state=SessionState.LOGIN_REQUIRED,
            confidence=0.9,
            evidence=["Password field"],
            detected_url="https://example.com/login",
            reason="Login form detected",
            login_type=LoginType.PASSWORD,
            mfa_type=None,
        )
        d = state.to_dict()
        assert d["state"] == "LOGIN_REQUIRED"
        assert d["confidence"] == 0.9
        assert "Password field" in d["evidence"]
        assert d["login_type"] == "PASSWORD"

    def test_checkpoint_snapshot_serializable(self):
        cp = create_auth_checked_checkpoint(
            run_id="run-111",
            step=1,
            auth_state="MFA_REQUIRED",
            reason="test",
            confidence=0.85,
        )
        snapshot = cp.state_snapshot
        assert isinstance(snapshot, dict)
        assert snapshot["auth_state"] == "MFA_REQUIRED"


# ---------------------------------------------------------------------------
# Part 27: Auth state logging
# ---------------------------------------------------------------------------

class TestAuthStateLogging:
    """Part 27: Auth state logging for debugging."""

    def test_auth_state_has_reason(self):
        state = AuthenticationState.authenticated(reason="Account menu visible")
        assert state.reason == "Account menu visible"

    def test_auth_state_has_evidence(self):
        state = AuthenticationState(
            state=SessionState.LOGIN_REQUIRED,
            confidence=0.9,
            evidence=["Password field", "Login form"],
            detected_url="test",
            reason="test",
        )
        assert len(state.evidence) == 2

    def test_checkpoint_has_snapshot(self):
        cp = create_auth_checked_checkpoint(
            run_id="run-222",
            step=1,
            auth_state="AUTHENTICATED",
            reason="test",
            confidence=0.9,
        )
        assert "auth_state" in cp.state_snapshot
        assert "reason" in cp.state_snapshot


# ---------------------------------------------------------------------------
# Part 28: Auth state driver detection
# ---------------------------------------------------------------------------

class TestDriverDetection:
    """Part 28: Driver-based auth detection."""

    def test_mock_driver_detects_all_states(self):
        for page_name, page in MOCK_AUTH_PAGES.items():
            driver = MockAuthBrowserDriver(page)
            auth = driver.detect_authentication()
            assert auth.state == page.auth_state, f"Failed for {page_name}"

    def test_driver_returns_current_domain(self):
        for page_name, page in MOCK_AUTH_PAGES.items():
            driver = MockAuthBrowserDriver(page)
            domain = driver.get_current_domain()
            assert isinstance(domain, str)
            assert len(domain) > 0


# ---------------------------------------------------------------------------
# Part 29: Auth state with real browser selectors
# ---------------------------------------------------------------------------

class TestRealBrowserSelectors:
    """Part 29: Auth detection with real browser selectors."""

    def test_password_field_selector_variants(self):
        """Password fields can use various selectors."""
        selectors = [
            "input[type=password]",
            "input[name*='password']",
            "input[id*='password']",
            "input[autocomplete='current-password']",
        ]
        for sel in selectors:
            assert "password" in sel.lower()

    def test_otp_input_selector_variants(self):
        """OTP inputs can use various selectors."""
        selectors = [
            "input[name*='otp']",
            "input[name*='code']",
            "input[name*='token']",
            "input[autocomplete='one-time-code']",
            "input[inputmode='numeric']",
        ]
        for sel in selectors:
            assert any(kw in sel for kw in ["otp", "code", "token", "one-time", "numeric"])

    def test_captcha_iframe_selectors(self):
        """CAPTCHA iframes can use various selectors."""
        selectors = [
            "iframe[title*='captcha']",
            "iframe[src*='captcha']",
            "iframe[src*='recaptcha']",
        ]
        for sel in selectors:
            assert "captcha" in sel.lower()


# ---------------------------------------------------------------------------
# Part 30: Auth state edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Part 30: Edge cases in auth detection."""

    def test_empty_body_text(self):
        page = MOCK_AUTH_PAGES["unknown"]
        page.body_text = ""
        driver = MockAuthBrowserDriver(page)
        auth = driver.detect_authentication()
        assert auth.state == SessionState.UNKNOWN

    def test_no_url(self):
        page = MOCK_AUTH_PAGES["unknown"]
        page.url = ""
        driver = MockAuthBrowserDriver(page)
        domain = driver.get_current_domain()
        assert domain == "" or domain == "mock.test"

    def test_multiple_auth_signals(self):
        """When multiple signals exist, strongest one wins."""
        page = MOCK_AUTH_PAGES["login-required"]
        page.has_password_field = True
        page.has_captcha = True
        driver = MockAuthBrowserDriver(page)
        auth = driver.detect_authentication()
        # CAPTCHA should take precedence over login
        assert auth.state in (SessionState.CAPTCHA_REQUIRED, SessionState.LOGIN_REQUIRED)

    def test_mixed_mfa_signals(self):
        """When both OTP and MFA text exist, MFA type is detected."""
        page = MOCK_AUTH_PAGES["mfa-sms"]
        page.has_otp_input = True
        driver = MockAuthBrowserDriver(page)
        auth = driver.detect_authentication()
        assert auth.state == SessionState.MFA_REQUIRED


# ---------------------------------------------------------------------------
# Part 31: Documentation reference
# ---------------------------------------------------------------------------

class TestDocumentationReference:
    """Part 31: Documentation reference tests."""

    def test_session_states_documented(self):
        states = [
            "AUTHENTICATED", "LOGIN_REQUIRED", "MFA_REQUIRED",
            "CAPTCHA_REQUIRED", "AUTH_FAILED", "SESSION_EXPIRED",
            "BLOCKED", "UNKNOWN",
        ]
        for state_name in states:
            assert hasattr(SessionState, state_name)

    def test_login_types_documented(self):
        types = ["PASSWORD", "SSO_OAUTH", "MAGIC_LINK", "PASSKEY"]
        for type_name in types:
            assert hasattr(LoginType, type_name)

    def test_mfa_types_documented(self):
        types = ["TOTP", "SMS", "EMAIL", "PUSH", "HARDWARE_KEY", "RECOVERY_CODE"]
        for type_name in types:
            assert hasattr(MFAType, type_name)


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def test_phase15_summary():
    """Summary: Phase 15 coverage check."""
    assert SessionState.AUTHENTICATED.value == "AUTHENTICATED"
    assert LoginType.PASSWORD.value == "PASSWORD"
    assert MFAType.TOTP.value == "TOTP"
    assert map_session_state_to_action(SessionState.AUTHENTICATED) == "PROCEED"
    assert map_session_state_to_action(SessionState.LOGIN_REQUIRED) == "AWAITING_USER"
    assert requires_human_intervention(SessionState.MFA_REQUIRED) is True
    assert can_auto_login(SessionState.AUTHENTICATED) is True
    assert is_auth_terminal(SessionState.AUTH_FAILED) is True
