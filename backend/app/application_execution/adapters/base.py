"""Adapter base + registry (Phase 7).

A :class:`PlatformAdapter` exposes, per platform:

* ``platform`` / ``display_name`` ids;
* ``resolve_mode(stored_policies)`` -- the ONE place a platform learns its mode
  (it never re-decides policy itself; it only reads the policy engine output);
* ``field_hints()`` -- platform-specific label → canonical field hints that
  fall back to the generic mapper;
* ``capabilities(mode)`` -- which operations are allowed for this platform in
  this mode;
* ``guidance(mode)`` -- user-facing text.

The registry returns the adapter for a detected platform; ``generic`` is the
fallback only when no other adapter matches, and ``human_assisted`` is the
skeleton every adapter leans on when its mode is HUMAN_ASSISTED.
"""
from __future__ import annotations

from app.application_execution import policy as policy_engine
from app.application_execution.base import PolicyDecision


class PlatformAdapter:
    platform: str = "generic"
    display_name: str = "Application page"
    _fallback_mode: str | None = None

    def resolve_mode(self, stored_policies: dict | None) -> str:
        """Mode for this platform, honoring stored configuration."""
        return policy_engine.resolve_policy(self.platform, stored_policies).mode

    def policy(self, stored_policies: dict | None) -> PolicyDecision:
        return policy_engine.resolve_policy(self.platform, stored_policies)

    # -- capabilities -------------------------------------------------------

    def allows_inspect(self, mode: str) -> bool:
        return True  # merely opening/reading the public page is always lawful to attempt

    def allows_fill_known(self, mode: str) -> bool:
        return mode in ("AUTHORIZED_AUTOMATION", "PERMITTED_BROWSER", "HUMAN_ASSISTED")

    def allows_resume_upload(self, mode: str) -> bool:
        return mode in ("AUTHORIZED_AUTOMATION", "PERMITTED_BROWSER", "HUMAN_ASSISTED")

    def allows_automated_submit(self, mode: str) -> bool:
        return mode in ("AUTHORIZED_AUTOMATION", "PERMITTED_BROWSER")

    # -- data ---------------------------------------------------------------

    def field_hints(self) -> list[tuple[str, str]]:
        """Extra (label, canonical-key) hints for this platform."""
        return []

    def form_specifics(self) -> list[tuple[str, str]]:
        """Text guidance about this platform's form peculiarities."""
        return []

    def guidance(self, mode: str) -> str:
        return (
            "Inspect the page and fill known fields only when the execution "
            "policy for this platform allows it. Stop before submission for "
            "human review."
        )


_REGISTRY: dict[str, type[PlatformAdapter]] = {}


def register(adapter: type[PlatformAdapter]) -> type[PlatformAdapter]:
    _REGISTRY[adapter.platform] = adapter
    return adapter


def get_adapter(platform: str) -> PlatformAdapter:
    cls = _REGISTRY.get(platform, _REGISTRY["generic"])
    return cls()


def list_adapters() -> list[str]:
    return list(_REGISTRY.keys())


