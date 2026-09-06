"""LinkedIn adapter (Phase 7).

LinkedIn's Easy Apply is a multi-step flow with frequent, user-facing
challenges. Nothing here asserts what LinkedIn legally or technically permits:
the policy engine decides the mode, and this adapter only pins down safe
default field hints and guidance. Automated submission is never assumed.
"""
from app.application_execution.adapters.base import PlatformAdapter, register


@register
class LinkedInAdapter(PlatformAdapter):
    platform = "linkedin"
    display_name = "LinkedIn"

    def field_hints(self) -> list[tuple[str, str]]:
        return [
            ("linkedin profile url", "linkedin_url"),
            ("your linkedin url", "linkedin_url"),
            ("headline", "linkedin_url"),
        ]

    def form_specifics(self) -> list[tuple[str, str]]:
        return [
            (
                "easy-apply",
                "LinkedIn Easy Apply is a multi-step flow; the engine stops "
                "between steps and after any challenge.",
            ),
            (
                "screening",
                "Screening questions may appear that were not prepared; the "
                "engine surfaces them instead of guessing.",
            ),
        ]

    def guidance(self, mode: str) -> str:
        if mode == "HUMAN_ASSISTED":
            return (
                "Walk the Easy Apply flow with the browser open. The engine "
                "filled what it could and uploaded the approved resume; you "
                "complete and submit yourself."
            )
        if mode in ("AUTHORIZED_AUTOMATION", "PERMITTED_BROWSER"):
            return (
                "Proceeding step by step with a human-confirmed submission. "
                "Any CAPTCHA or login wall stops the run immediately."
            )
        return "Open the job page and stop: this platform is not supported for automation."
