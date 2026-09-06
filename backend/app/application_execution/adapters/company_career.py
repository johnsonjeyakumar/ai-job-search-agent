"""Company career-site adapter (Phase 7).

Career portals (Greenhouse/Lever/Workday and company apply pages) get ordinary
browser automation where that is technically possible and the mode permits it.
Like every adapter, it never guesses on ambiguous fields and always stops at
the human approval boundary before submission.
"""
from app.application_execution.adapters.base import PlatformAdapter, register


@register
class CompanyCareerAdapter(PlatformAdapter):
    platform = "company_career"
    display_name = "Company career site"

    def field_hints(self) -> list[tuple[str, str]]:
        return [
            ("first name", "first_name"),
            ("last name", "last_name"),
            ("email address", "email"),
            ("linkedin profile url", "linkedin_url"),
            ("website", "portfolio_url"),
            ("resume/cv", "resume"),
        ]

    def form_specifics(self) -> list[tuple[str, str]]:
        return [
            (
                "ats",
                "Company ATS forms often include custom screening questions. "
                "Anything not prepared surfaces as a NEW QUESTION and stops the run.",
            ),
        ]

    def guidance(self, mode: str) -> str:
        if mode in ("AUTHORIZED_AUTOMATION", "PERMITTED_BROWSER"):
            return (
                "Ordinary single-page apply is automated step by step; "
                "submission waits for your explicit approval."
            )
        return (
            "The engine fills the standard fields and uploads the approved "
            "resume, then stops for you to submit."
        )
