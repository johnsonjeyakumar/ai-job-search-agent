"""Indeed adapter (Phase 7).

Indeed application forms typically include wage/availability follow-ups and
can be blocked by anti-bot checks. The adapter leans on the policy engine for
the mode and never assumes automated submission is permitted.
"""
from app.application_execution.adapters.base import PlatformAdapter, register


@register
class IndeedAdapter(PlatformAdapter):
    platform = "indeed"
    display_name = "Indeed"

    def field_hints(self) -> list[tuple[str, str]]:
        return [
            ("your email", "email"),
            ("phone number", "phone"),
            ("desired wage", "salary"),
            ("salary expectation", "salary"),
        ]

    def form_specifics(self) -> list[tuple[str, str]]:
        return [
            ("follow-up", "Indeed may ask wage/availability follow-ups; they "
             "are treated as new questions and surfaced for review."),
        ]

    def guidance(self, mode: str) -> str:
        if mode == "HUMAN_ASSISTED":
            return (
                "Indeed forms frequently require a manual wage/availability "
                "step. The engine fills known fields and uploads the approved "
                "resume, then hands control to you."
            )
        return (
            "Proceeding with a human-confirmed submission. Anti-bot checks or a "
            "login wall stop the run immediately."
        )
