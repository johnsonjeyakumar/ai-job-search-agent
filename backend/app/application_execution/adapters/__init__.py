"""Platform adapters (Phase 7).

Each adapter owns the policy-facing knowledge for ONE platform: what the
platform is, what its safe automation envelope is, and what guidance to give
the user. Execution mechanics (open, inspect, map, fill, verify) stay in the
shared runner; the adapter decides whether each mechanical step is lawful for
its platform in the current mode. There is deliberately no
``apply_everywhere()`` -- the runner only ever drives the adapter selected by
detection.
"""
from app.application_execution.adapters import (  # noqa: F401 - registers adapters
    company_career,
    generic,
    human_assisted,
    indeed,
    linkedin,
    naukri,
)
from app.application_execution.adapters.base import (
    PlatformAdapter,
    get_adapter,
    list_adapters,
)

__all__ = ["PlatformAdapter", "get_adapter", "list_adapters"]
