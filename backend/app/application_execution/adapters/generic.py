"""Generic application-page adapter (Phase 7).

Only used for pages with no better classification. The engine inspects and maps
fields but refuses to treat every random site as applicable: ambiguous or
unknown controls always surface for review, and submission always stops at the
human approval boundary.
"""
from app.application_execution.adapters.base import PlatformAdapter, register


@register
class GenericAdapter(PlatformAdapter):
    platform = "generic"
    display_name = "Application page"

    def allows_automated_submit(self, mode: str) -> bool:
        # Generic pages are never auto-submitted, even in PERMITTED_BROWSER:
        # their semantics are unverified.
        return False

    def guidance(self, mode: str) -> str:
        return (
            "This page could not be positively identified as a known board. "
            "Known fields are filled from your profile and the approved resume "
            "is uploaded only after review; anything ambiguous stops the run."
        )
