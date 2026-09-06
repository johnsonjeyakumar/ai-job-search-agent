"""Human-assisted adapter (Phase 7).

Used directly when a platform's policy is HUMAN_ASSISTED. The engine does the
safe part (open, inspect, map, fill known fields, upload the approved resume)
and then stops: the human completes and submits manually in the browser.
"""
from app.application_execution.adapters.base import PlatformAdapter, register


@register
class HumanAssistedAdapter(PlatformAdapter):
    platform = "human_assisted"
    display_name = "Human-assisted application"

    def allows_automated_submit(self, mode: str) -> bool:
        return False

    def guidance(self, mode: str) -> str:
        return (
            "The engine prepared the form for you: fields were filled from "
            "your profile and the approved resume was uploaded. Finish the "
            "remaining steps yourself in the browser and submit manually."
        )
