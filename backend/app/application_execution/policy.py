"""Deterministic execution policy (Phase 7).

Every platform maps to exactly one execution mode. The mapping below is the
SAFE DEFAULT only -- none of it is asserted as legal fact, and every value can
be overridden by the user's stored ``platform_policies`` configuration.

Mode semantics:

* ``AUTHORIZED_AUTOMATION`` -- an officially authorized/API path exists for the
  platform. Not assumed for any built-in platform by default.
* ``PERMITTED_BROWSER`` -- ordinary browser interaction may be used for safe
  steps; final submission still requires explicit human approval.
* ``HUMAN_ASSISTED`` -- the engine may open/inspect/fill safe fields and upload
  the approved resume, but the human completes and submits manually.
* ``UNSUPPORTED`` -- the engine opens the page for inspection only and stops.
"""
from __future__ import annotations

from app.application_execution import base

# Safe defaults. Deliberately permissive about a couple of *capture* actions
# (open/inspect/fill known fields) and never permissive about final submission.
DEFAULT_PLATFORM_POLICIES: dict[str, str] = {
    "linkedin": base.HUMAN_ASSISTED,
    "indeed": base.HUMAN_ASSISTED,
    "naukri": base.HUMAN_ASSISTED,
    "company_career": base.PERMITTED_BROWSER,
    "generic": base.PERMITTED_BROWSER,
}

_AUTO_SUBMIT_MODES = {base.AUTHORIZED_AUTOMATION, base.PERMITTED_BROWSER}
_BROWSER_MODES = {base.AUTHORIZED_AUTOMATION, base.PERMITTED_BROWSER, base.HUMAN_ASSISTED}


class PolicyResolver:
    """Resolves and validates a platform's execution mode."""

    def __init__(self, defaults: dict[str, str] | None = None):
        self.defaults = defaults or dict(DEFAULT_PLATFORM_POLICIES)

    def resolve(self, platform: str, stored_policies: dict | None = None) -> base.PolicyDecision:
        mode = self._pick_mode(platform, stored_policies or {})
        if mode not in base.EXECUTION_MODES:
            mode = base.HUMAN_ASSISTED

        supports_browser = mode in _BROWSER_MODES
        supports_auto_submit = mode in _AUTO_SUBMIT_MODES
        requires_approval = supports_browser

        source = "stored configuration" if (platform in (stored_policies or {})) else "safe default"
        return base.PolicyDecision(
            platform=platform,
            mode=mode,
            reason=f"Policy resolved from {source} ({mode}).",
            supports_browser_automation=supports_browser,
            supports_automated_submit=supports_auto_submit,
            requires_user_approval=requires_approval,
        )

    def _pick_mode(self, platform: str, stored_policies: dict) -> str:
        if platform in stored_policies:
            return str(stored_policies[platform]).upper()
        return self.defaults.get(platform, base.HUMAN_ASSISTED)


def resolve_policy(
    platform: str, stored_policies: dict | None = None, defaults: dict | None = None
) -> base.PolicyDecision:
    return PolicyResolver(defaults).resolve(platform, stored_policies)
