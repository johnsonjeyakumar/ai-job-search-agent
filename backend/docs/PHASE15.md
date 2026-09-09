# Phase 15: Login / Session / 2FA Handling

## Overview

Phase 15 adds session/authentication awareness to the application executor. The system detects authentication states using multiple signals and maps them to execution actions, ensuring safe, human-in-the-loop handling of login, MFA, and CAPTCHA challenges.

## Safety Rules

- **NEVER** stores passwords, OTPs, cookies, tokens, or browser secrets
- Session metadata is non-sensitive (platform, login type, timestamps)
- All detection is signal-based, not credential-based
- Human intervention is required for all authentication challenges

## Architecture

### Authentication State Machine

```
UNKNOWN ──────────────────────────────────────────────────────────┐
   │                                                              │
   ▼                                                              │
AUTHENTICATED ◄──────────────────────────────────────────────┐    │
   │                                                         │    │
   ▼                                                         │    │
LOGIN_REQUIRED ──► MFA_REQUIRED ──► AUTHENTICATED           │    │
   │                   │                                     │    │
   ▼                   ▼                                     │    │
AUTH_FAILED         CAPTCHA_REQUIRED                         │    │
   │                   │                                     │    │
   ▼                   ▼                                     │    │
BLOCKED             SESSION_EXPIRED ──► LOGIN_REQUIRED ──────┘    │
                                                        │        │
                                                        └────────┘
```

### Session States

| State | Description | Action |
|-------|-------------|--------|
| `UNKNOWN` | No reliable indicators found | PROCEED_WITH_WARNING |
| `AUTHENTICATED` | User is logged in | PROCEED |
| `LOGIN_REQUIRED` | Login form detected | AWAITING_USER |
| `MFA_REQUIRED` | MFA/2FA prompt detected | AWAITING_USER |
| `CAPTCHA_REQUIRED` | CAPTCHA challenge detected | AWAITING_USER |
| `AUTH_FAILED` | Authentication error detected | BLOCKED |
| `SESSION_EXPIRED` | Session timeout detected | BLOCKED |
| `BLOCKED` | Account locked or restricted | BLOCKED |

### Login Types

- `PASSWORD` - Traditional username/password
- `SSO_OAUTH` - Single Sign-On (Google, LinkedIn, etc.)
- `MAGIC_LINK` - Email magic link
- `PASSKEY` - WebAuthn/FIDO2
- `SOCIAL` - Social login
- `UNKNOWN` - Unable to determine

### MFA Types

- `TOTP` - Time-based One-Time Password (authenticator app)
- `SMS` - SMS verification code
- `EMAIL` - Email verification code
- `PUSH` - Push notification
- `HARDWARE_KEY` - FIDO2/WebAuthn hardware key
- `RECOVERY_CODE` - Backup recovery code
- `UNKNOWN` - Unable to determine

## Detection Signals

### Password Field Detection
- `input[type=password]`
- `input[name*='password']`
- `input[id*='password']`
- `input[autocomplete='current-password']`

### MFA/2FA Detection
- Text signals: "enter the code", "verification code", "2fa", "authenticator"
- Input fields: `input[name*='otp']`, `input[autocomplete='one-time-code']`

### OAuth/SSO Detection
- Text signals: "sign in with", "continue with", "google", "linkedin"
- Button selectors: `button[class*='google']`, `a[href*='oauth']`

### CAPTCHA Detection
- Iframe selectors: `iframe[title*='captcha']`, `iframe[src*='recaptcha']`
- Input selectors: `input[name*='captcha']`, `#captcha`

### Auth Error Detection
- Text signals: "invalid credentials", "incorrect password", "login failed"

### Session Expiry Detection
- Text signals: "session expired", "please log in again", "access denied"

### Authenticated Indicators
- Text signals: "logout", "sign out", "my account", "dashboard"

## Checkpoint Types

| Checkpoint | Description |
|------------|-------------|
| `AUTH_CHECKED` | Authentication state checked |
| `LOGIN_REQUIRED` | Login is required |
| `LOGIN_COMPLETED` | Login completed successfully |
| `MFA_REQUIRED` | MFA/2FA is required |
| `SESSION_EXPIRED` | Session has expired |
| `SESSION_RESTORED` | Session restored |
| `AUTH_FAILED` | Authentication failed |
| `DOMAIN_VALIDATED` | Domain validated |

## Integration Points

### Executor Integration

1. **Initial Auth Check**: After opening the application URL, check authentication state
2. **Post-Navigation Auth Check**: After navigating to each page in multi-page forms
3. **State Mapping**: Map session states to execution actions
4. **Checkpoint Creation**: Save auth checkpoints for debugging and recovery

### Browser Driver Interface

```python
def detect_authentication() -> AuthenticationState:
    """Detect the current authentication state."""
    ...

def get_current_domain() -> str:
    """Get the current domain for session fixation protection."""
    ...
```

## Configuration

### Constants

- `MAX_AUTH_DETECTION_RETRIES = 3` - Maximum retry attempts for detection
- `AUTH_WAIT_TIMEOUT_SECONDS = 300` - Timeout for human login/MFA completion
- `AUTH_CHECK_INTERVAL_SECONDS = 5` - Interval for re-checking state

## Testing

### Mock Auth Pages

The test suite includes 10 mock authentication pages:

1. `authenticated` - User is logged in
2. `login-required` - Password login required
3. `sso-required` - SSO/OAuth required
4. `mfa-totp` - TOTP MFA required
5. `mfa-sms` - SMS MFA required
6. `mfa-email` - Email MFA required
7. `captcha` - CAPTCHA challenge
8. `auth-failed` - Authentication failed
9. `session-expired` - Session expired
10. `unknown` - No indicators found

### Test Coverage

- Session state model
- Authentication state dataclass
- Login and MFA type enums
- State mapping functions
- Helper functions
- Mock browser auth detection
- Checkpoint creation
- Executor integration
- Domain validation
- Confidence thresholds
- CAPTCHA interaction
- Session expiry handling
- MFA/2FA handling
- SSO/OAuth handling
- Login type detection
- Evidence collection
- URL-based detection
- Multi-page form auth checks
- Checkpoint integrity
- State machine transitions
- Auto-login prevention
- Error recovery
- Page URL capture
- Cross-origin protection
- Auth state serialization
- Auth state logging
- Driver detection
- Real browser selectors
- Edge cases
- Documentation reference

## Files

- `app/application_execution/auth.py` - Authentication state model
- `app/application_execution/browser.py` - Browser driver with auth detection
- `app/application_execution/executor.py` - Execution runner with auth integration
- `app/application_execution/checkpoint.py` - Auth checkpoint types
- `tests/mock_auth_pages.py` - Mock authentication pages
- `tests/test_phase15_auth.py` - Comprehensive test suite
