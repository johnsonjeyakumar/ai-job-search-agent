"""Form session model for multi-step application orchestration (Phase 14).

Tracks the state of a multi-page application form across page transitions,
navigation actions, and dynamic field changes. Each execution run creates
at most one FormSession, and the session persists across page boundaries.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum

from app.application_execution.base import DetectedField

# ---------------------------------------------------------------------------
# Page types
# ---------------------------------------------------------------------------

class PageType(str, Enum):
    FORM_PAGE = "FORM_PAGE"
    REVIEW_PAGE = "REVIEW_PAGE"
    SUBMISSION_PAGE = "SUBMISSION_PAGE"
    UNKNOWN_PAGE = "UNKNOWN_PAGE"


# ---------------------------------------------------------------------------
# Navigation actions
# ---------------------------------------------------------------------------

class NavigationAction(str, Enum):
    NEXT_PAGE = "NEXT_PAGE"
    SAVE_AND_CONTINUE = "SAVE_AND_CONTINUE"
    PREVIOUS_PAGE = "PREVIOUS_PAGE"
    REVIEW = "REVIEW"
    SUBMIT = "SUBMIT"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Form session states
# ---------------------------------------------------------------------------

class FormSessionState(str, Enum):
    DISCOVERING = "DISCOVERING"
    PAGE_INSPECTED = "PAGE_INSPECTED"
    PAGE_READY = "PAGE_READY"
    FIELDS_MAPPED = "FIELDS_MAPPED"
    FIELDS_FILLED = "FIELDS_FILLED"
    PAGE_VALIDATED = "PAGE_VALIDATED"
    WAITING_USER = "WAITING_USER"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    NAVIGATING = "NAVIGATING"
    REVIEW = "REVIEW"
    READY_TO_SUBMIT = "READY_TO_SUBMIT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Field tracking states
# ---------------------------------------------------------------------------

class FieldState(str, Enum):
    DISCOVERED = "DISCOVERED"
    MAPPED = "MAPPED"
    FILLED = "FILLED"
    VALIDATED = "VALIDATED"
    CHANGED = "CHANGED"
    INVALIDATED = "INVALIDATED"
    REMOVED = "REMOVED"


# ---------------------------------------------------------------------------
# Navigation signals
# ---------------------------------------------------------------------------

_NEXT_TEXTS = {
    "next", "continue", "save & continue", "save and continue",
    "proceed", "continue application", "go to next step",
    "next step", "next page", "save & next", "save and next",
}
_BACK_TEXTS = {"back", "previous", "go back", "previous step"}
_REVIEW_TEXTS = {"review", "review application", "review & submit", "review and submit"}
_SUBMIT_TEXTS = {"submit", "submit application", "apply", "send application"}


# ---------------------------------------------------------------------------
# Page fingerprinting
# ---------------------------------------------------------------------------

def compute_page_fingerprint(
    url: str,
    heading: str | None = None,
    step_indicator: str | None = None,
    field_labels: list[str] | None = None,
) -> str:
    """Compute a stable fingerprint for a form page.

    Uses URL + heading + step indicator + sorted field labels.
    This allows re-identification after browser refresh/restart.
    """
    parts = [url.lower().rstrip("/")]
    if heading:
        parts.append(heading.lower().strip())
    if step_indicator:
        parts.append(step_indicator.lower().strip())
    if field_labels:
        parts.extend(sorted(lbl.lower().strip() for lbl in field_labels))
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Tracked field
# ---------------------------------------------------------------------------

@dataclass
class TrackedField:
    """A form field tracked across the lifecycle of a page."""
    detected: DetectedField
    canonical: str | None = None
    value: str | None = None
    state: FieldState = FieldState.DISCOVERED
    confidence: float = 0.0
    sensitivity: str = "LOW"
    required: bool = False
    originally_required: bool = False
    parent_question: str | None = None
    is_conditional: bool = False
    visible: bool = True

    def fingerprint(self) -> str:
        raw = f"{self.detected.label}|{self.detected.kind}|{self.required}"
        return hashlib.sha256(raw.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# Page snapshot
# ---------------------------------------------------------------------------

@dataclass
class PageSnapshot:
    """Captured state of a single form page."""
    page_index: int
    page_key: str
    page_type: PageType
    url: str
    heading: str | None = None
    step_indicator: str | None = None
    fingerprint: str = ""
    fields: list[TrackedField] = field(default_factory=list)
    navigation: NavigationAction = NavigationAction.NONE
    has_next_button: bool = False
    has_back_button: bool = False
    has_submit_button: bool = False
    has_review_button: bool = False
    next_button_selector: str | None = None
    back_button_selector: str | None = None
    submit_button_selector: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    required_fields_count: int = 0
    filled_fields_count: int = 0
    discovered_at: float = 0.0
    inspected_at: float = 0.0

    @property
    def is_complete(self) -> bool:
        """All required fields are filled."""
        required = [f for f in self.fields if f.required and f.visible]
        return all(f.value is not None for f in required)

    @property
    def field_fingerprints(self) -> set[str]:
        return {f.fingerprint() for f in self.fields if f.visible}

    def detect_changes(self, other: PageSnapshot) -> dict:
        """Compare with another snapshot and report changes."""
        self_fps = self.field_fingerprints
        other_fps = other.field_fingerprints
        added = [f for f in other.fields if f.fingerprint() not in self_fps and f.visible]
        removed = [f for f in self.fields if f.fingerprint() not in other_fps and f.visible]
        changed_required = [
            f for f in other.fields
            if f.fingerprint() in self_fps
            and f.required != any(
                s.fingerprint() == f.fingerprint() and s.required
                for s in self.fields
            )
        ]
        return {
            "added_fields": added,
            "removed_fields": removed,
            "changed_required": changed_required,
            "has_changes": bool(added or removed or changed_required),
        }


# ---------------------------------------------------------------------------
# Form session
# ---------------------------------------------------------------------------

@dataclass
class FormSession:
    """Tracks multi-page form state across page transitions.

    One FormSession per execution run. Persists across pages until
    the application is submitted or the run terminates.
    """
    session_id: str = ""
    application_id: int | None = None
    execution_run_id: int | None = None
    package_id: int | None = None
    current_page_index: int = 0
    current_page_key: str = ""
    page_count: int = 0
    page_type: PageType = PageType.UNKNOWN_PAGE
    status: FormSessionState = FormSessionState.DISCOVERING
    pages: dict[str, PageSnapshot] = field(default_factory=dict)
    page_order: list[str] = field(default_factory=list)
    visited_pages: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error_message: str | None = None
    retry_count: int = 0
    navigation_history: list[dict] = field(default_factory=list)

    # --- Page management ---

    def add_page(self, snapshot: PageSnapshot) -> None:
        key = snapshot.page_key
        self.pages[key] = snapshot
        if key not in self.page_order:
            self.page_order.append(key)
        self.visited_pages.add(key)
        self.page_count = len(self.page_order)
        self.updated_at = time.time()

    def get_current_page(self) -> PageSnapshot | None:
        return self.pages.get(self.current_page_key)

    def set_current_page(self, page_key: str) -> PageSnapshot | None:
        if page_key in self.pages:
            self.current_page_key = page_key
            self.current_page_index = self.page_order.index(page_key)
            self.updated_at = time.time()
            return self.pages[page_key]
        return None

    def advance_page(self) -> PageSnapshot | None:
        next_index = self.current_page_index + 1
        if next_index < len(self.page_order):
            key = self.page_order[next_index]
            return self.set_current_page(key)
        return None

    def retreat_page(self) -> PageSnapshot | None:
        prev_index = self.current_page_index - 1
        if prev_index >= 0:
            key = self.page_order[prev_index]
            return self.set_current_page(key)
        return None

    # --- Navigation tracking ---

    def record_navigation(self, action: NavigationAction, from_page: str, to_page: str) -> None:
        self.navigation_history.append({
            "action": action.value,
            "from_page": from_page,
            "to_page": to_page,
            "timestamp": time.time(),
        })
        self.updated_at = time.time()

    # --- State transitions ---

    def transition(self, new_state: FormSessionState) -> bool:
        valid = _TRANSITIONS.get(self.status, set())
        if new_state in valid:
            self.status = new_state
            self.updated_at = time.time()
            return True
        return False

    # --- Serialization ---

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "application_id": self.application_id,
            "execution_run_id": self.execution_run_id,
            "package_id": self.package_id,
            "current_page_index": self.current_page_index,
            "current_page_key": self.current_page_key,
            "page_count": self.page_count,
            "page_type": self.page_type.value,
            "status": self.status.value,
            "visited_pages": sorted(self.visited_pages),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "navigation_count": len(self.navigation_history),
        }

    def to_checkpoint(self) -> dict:
        """Serialize for checkpoint storage."""
        pages_data = {}
        for key, snap in self.pages.items():
            pages_data[key] = {
                "page_index": snap.page_index,
                "page_key": snap.page_key,
                "page_type": snap.page_type.value,
                "url": snap.url,
                "heading": snap.heading,
                "fingerprint": snap.fingerprint,
                "fields": [
                    {
                        "label": f.detected.label,
                        "kind": f.detected.kind,
                        "canonical": f.canonical,
                        "value": f.value,
                        "state": f.state.value,
                        "required": f.required,
                        "visible": f.visible,
                        "is_conditional": f.is_conditional,
                        "parent_question": f.parent_question,
                    }
                    for f in snap.fields
                ],
                "has_next_button": snap.has_next_button,
                "has_back_button": snap.has_back_button,
                "has_submit_button": snap.has_submit_button,
                "has_review_button": snap.has_review_button,
                "validation_errors": snap.validation_errors,
            }
        return {
            "session_id": self.session_id,
            "application_id": self.application_id,
            "execution_run_id": self.execution_run_id,
            "package_id": self.package_id,
            "current_page_index": self.current_page_index,
            "current_page_key": self.current_page_key,
            "page_count": self.page_count,
            "page_type": self.page_type.value,
            "status": self.status.value,
            "visited_pages": sorted(self.visited_pages),
            "pages": pages_data,
            "page_order": self.page_order,
            "navigation_history": self.navigation_history,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_checkpoint(cls, data: dict) -> FormSession:
        """Restore from checkpoint data."""
        session = cls(
            session_id=data.get("session_id", ""),
            application_id=data.get("application_id"),
            execution_run_id=data.get("execution_run_id"),
            package_id=data.get("package_id"),
            current_page_index=data.get("current_page_index", 0),
            current_page_key=data.get("current_page_key", ""),
            page_count=data.get("page_count", 0),
            page_type=PageType(data.get("page_type", "UNKNOWN_PAGE")),
            status=FormSessionState(data.get("status", "DISCOVERING")),
            visited_pages=set(data.get("visited_pages", [])),
            navigation_history=data.get("navigation_history", []),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            page_order=data.get("page_order", []),
        )
        for key, page_data in data.get("pages", {}).items():
            fields = []
            for fd in page_data.get("fields", []):
                detected = DetectedField(
                    label=fd["label"],
                    kind=fd["kind"],
                    required=fd.get("required", False),
                )
                fields.append(TrackedField(
                    detected=detected,
                    canonical=fd.get("canonical"),
                    value=fd.get("value"),
                    state=FieldState(fd.get("state", "DISCOVERED")),
                    required=fd.get("required", False),
                    visible=fd.get("visible", True),
                    is_conditional=fd.get("is_conditional", False),
                    parent_question=fd.get("parent_question"),
                ))
            snap = PageSnapshot(
                page_index=page_data.get("page_index", 0),
                page_key=page_data.get("page_key", key),
                page_type=PageType(page_data.get("page_type", "UNKNOWN_PAGE")),
                url=page_data.get("url", ""),
                heading=page_data.get("heading"),
                fingerprint=page_data.get("fingerprint", ""),
                fields=fields,
                has_next_button=page_data.get("has_next_button", False),
                has_back_button=page_data.get("has_back_button", False),
                has_submit_button=page_data.get("has_submit_button", False),
                has_review_button=page_data.get("has_review_button", False),
                validation_errors=page_data.get("validation_errors", []),
            )
            session.pages[key] = snap
        return session


# ---------------------------------------------------------------------------
# Valid state transitions
# ---------------------------------------------------------------------------

_TRANSITIONS: dict[FormSessionState, set[FormSessionState]] = {
    FormSessionState.DISCOVERING: {
        FormSessionState.PAGE_INSPECTED,
        FormSessionState.FAILED,
        FormSessionState.BLOCKED,
    },
    FormSessionState.PAGE_INSPECTED: {
        FormSessionState.PAGE_READY,
        FormSessionState.WAITING_USER,
        FormSessionState.FAILED,
    },
    FormSessionState.PAGE_READY: {
        FormSessionState.FIELDS_MAPPED,
        FormSessionState.WAITING_USER,
        FormSessionState.FAILED,
    },
    FormSessionState.FIELDS_MAPPED: {
        FormSessionState.FIELDS_FILLED,
        FormSessionState.WAITING_USER,
        FormSessionState.FAILED,
    },
    FormSessionState.FIELDS_FILLED: {
        FormSessionState.PAGE_VALIDATED,
        FormSessionState.WAITING_USER,
        FormSessionState.FAILED,
    },
    FormSessionState.PAGE_VALIDATED: {
        FormSessionState.NAVIGATING,
        FormSessionState.REVIEW,
        FormSessionState.READY_TO_SUBMIT,
        FormSessionState.WAITING_USER,
        FormSessionState.WAITING_APPROVAL,
        FormSessionState.FAILED,
    },
    FormSessionState.WAITING_USER: {
        FormSessionState.PAGE_READY,
        FormSessionState.FIELDS_MAPPED,
        FormSessionState.BLOCKED,
        FormSessionState.FAILED,
    },
    FormSessionState.WAITING_APPROVAL: {
        FormSessionState.READY_TO_SUBMIT,
        FormSessionState.SUBMITTED,
        FormSessionState.FAILED,
    },
    FormSessionState.NAVIGATING: {
        FormSessionState.DISCOVERING,
        FormSessionState.PAGE_INSPECTED,
        FormSessionState.FAILED,
    },
    FormSessionState.REVIEW: {
        FormSessionState.READY_TO_SUBMIT,
        FormSessionState.NAVIGATING,
        FormSessionState.FAILED,
    },
    FormSessionState.READY_TO_SUBMIT: {
        FormSessionState.SUBMITTED,
        FormSessionState.WAITING_APPROVAL,
        FormSessionState.FAILED,
    },
    FormSessionState.SUBMITTED: {
        FormSessionState.CONFIRMED,
        FormSessionState.FAILED,
    },
    FormSessionState.CONFIRMED: set(),
    FormSessionState.BLOCKED: set(),
    FormSessionState.FAILED: set(),
}
