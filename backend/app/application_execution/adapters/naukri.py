"""Naukri adapter (Phase 7).

Naukri is account-centric: most applies go through a logged-in profile, so the
login wall is expected. This adapter therefore surfaces manual login/verification
and leans on the policy engine for the mode.
"""
from app.application_execution.adapters.base import PlatformAdapter, register


@register
class NaukriAdapter(PlatformAdapter):
    platform = "naukri"
    display_name = "Naukri"

    def field_hints(self) -> list[tuple[str, str]]:
        return [
            ("current location", "city"),
            ("years of experience", "experience_level"),
            ("current notice period", "notice_period"),
            ("expected salary", "salary"),
        ]

    def form_specifics(self) -> list[tuple[str, str]]:
        return [
            ("login", "Naukri applies usually require an existing logged-in "
             "session. The engine pauses and waits for manual login instead of "
             "storing credentials."),
        ]

    def guidance(self, mode: str) -> str:
        return (
            "Log in manually if prompted (credentials are never stored). The "
            "engine fills prepared fields and uploads the approved resume, then "
            "stops for your submission."
        )
