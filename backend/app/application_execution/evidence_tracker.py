"""Execution evidence recording (Phase 12).

Records evidence for every action taken during application execution.
Evidence is immutable and includes timestamps, before/after states,
and verification results. Used for audit, debugging, and analytics.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Evidence types
# ---------------------------------------------------------------------------
EVIDENCE_FIELD_FILLED = "FIELD_FILLED"
EVIDENCE_FIELD_SKIPPED = "FIELD_SKIPPED"
EVIDENCE_QUESTION_ANSWERED = "QUESTION_ANSWERED"
EVIDENCE_QUESTION_SKIPPED = "QUESTION_SKIPPED"
EVIDENCE_SUBMISSION_ATTEMPTED = "SUBMISSION_ATTEMPTED"
EVIDENCE_SUBMISSION_CONFIRMED = "SUBMISSION_CONFIRMED"
EVIDENCE_SUBMISSION_FAILED = "SUBMISSION_FAILED"
EVIDENCE_CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
EVIDENCE_HUMAN_APPROVAL = "HUMAN_APPROVAL"
EVIDENCE_ERROR = "ERROR"
EVIDENCE_RECOVERY = "RECOVERY"
EVIDENCE_CHECKPOINT = "CHECKPOINT"
EVIDENCE_MAPPING = "FIELD_MAPPING"
# Phase 16: file upload and advanced control evidence
EVIDENCE_FILE_UPLOADED = "FILE_UPLOADED"
EVIDENCE_FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"
EVIDENCE_FILE_VALIDATED = "FILE_VALIDATED"
EVIDENCE_FILE_VALIDATION_FAILED = "FILE_VALIDATION_FAILED"
EVIDENCE_CHECKBOX_TOGGLED = "CHECKBOX_TOGGLED"
EVIDENCE_RADIO_SELECTED = "RADIO_SELECTED"
EVIDENCE_MULTI_SELECT_CHANGED = "MULTI_SELECT_CHANGED"
EVIDENCE_AUTOCOMPLETE_SELECTED = "AUTOCOMPLETE_SELECTED"
EVIDENCE_DATE_FILLED = "DATE_FILLED"
EVIDENCE_CURRENCY_FILLED = "CURRENCY_FILLED"


@dataclass
class EvidenceRecord:
    """A single evidence record."""

    id: int | None = None
    run_id: str = ""
    evidence_type: str = ""
    timestamp: str = ""
    step_number: int = 0
    field_label: str | None = None
    canonical_name: str | None = None
    before_value: str | None = None
    after_value: str | None = None
    source: str = ""  # profile | memory | ai | user | auto
    confidence: str = ""  # HIGH | MEDIUM | LOW
    sensitivity: str = "LOW"
    verification_status: str = ""  # UNVERIFIED | USER_VERIFIED | SYSTEM_DERIVED
    success: bool = True
    error_message: str | None = None
    metadata: dict = field(default_factory=dict)
    data_hash: str = ""
    # Phase 16: advanced field metadata
    control_type: str | None = None  # text | select | radio | checkbox | file | date | multi_select | currency | autocomplete
    document_type: str | None = None  # for file uploads: resume | cover_letter | etc.
    uploaded_filename: str | None = None  # for file uploads
    validation_result: str | None = None  # for file uploads: VALID | INVALID | etc.
    verification_result: str | None = None  # for file uploads: CONFIRMED | FAILED | etc.
    page_identifier: str | None = None  # page URL or identifier

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        self.data_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute hash for integrity verification."""
        data = json.dumps({
            "run_id": self.run_id,
            "evidence_type": self.evidence_type,
            "step_number": self.step_number,
            "field_label": self.field_label,
            "before_value": self.before_value,
            "after_value": self.after_value,
            "timestamp": self.timestamp,
        }, sort_keys=True, default=str)
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class EvidenceStore:
    """Stores and manages execution evidence."""

    records: dict[str, list[EvidenceRecord]] = field(default_factory=dict)

    def record(self, evidence: EvidenceRecord) -> EvidenceRecord:
        """Record an evidence entry."""
        run_id = evidence.run_id
        if run_id not in self.records:
            self.records[run_id] = []

        evidence.id = len(self.records[run_id]) + 1
        self.records[run_id].append(evidence)
        return evidence

    def get_all(self, run_id: str) -> list[EvidenceRecord]:
        """Get all evidence for a run."""
        return self.records.get(run_id, [])

    def get_by_type(
        self, run_id: str, evidence_type: str
    ) -> list[EvidenceRecord]:
        """Get evidence of a specific type."""
        return [
            r for r in self.get_all(run_id)
            if r.evidence_type == evidence_type
        ]

    def get_by_field(
        self, run_id: str, field_label: str
    ) -> list[EvidenceRecord]:
        """Get evidence for a specific field."""
        return [
            r for r in self.get_all(run_id)
            if r.field_label == field_label
        ]

    def get_failures(self, run_id: str) -> list[EvidenceRecord]:
        """Get all failed evidence records."""
        return [
            r for r in self.get_all(run_id)
            if not r.success
        ]

    def verify_integrity(self, run_id: str) -> tuple[bool, list[str]]:
        """Verify integrity of all evidence records."""
        errors = []
        for record in self.get_all(run_id):
            expected_hash = record._compute_hash()
            if record.data_hash != expected_hash:
                errors.append(
                    f"Evidence record {record.id} hash mismatch: "
                    f"expected {expected_hash}, got {record.data_hash}"
                )
        return len(errors) == 0, errors

    def get_summary(self, run_id: str) -> dict:
        """Get a summary of evidence for a run."""
        records = self.get_all(run_id)
        return {
            "total_records": len(records),
            "successful": len([r for r in records if r.success]),
            "failed": len([r for r in records if not r.success]),
            "field_fills": len([
                r for r in records if r.evidence_type == EVIDENCE_FIELD_FILLED
            ]),
            "questions_answered": len([
                r for r in records if r.evidence_type == EVIDENCE_QUESTION_ANSWERED
            ]),
            "submissions": len([
                r for r in records if r.evidence_type == EVIDENCE_SUBMISSION_ATTEMPTED
            ]),
            "errors": len([
                r for r in records if r.evidence_type == EVIDENCE_ERROR
            ]),
        }

    def clear(self, run_id: str) -> None:
        """Clear all evidence for a run."""
        self.records.pop(run_id, None)


# ---------------------------------------------------------------------------
# Evidence creation helpers
# ---------------------------------------------------------------------------

def record_field_fill(
    store: EvidenceStore,
    run_id: str,
    step: int,
    field_label: str,
    canonical_name: str,
    before_value: str | None,
    after_value: str,
    source: str,
    confidence: str,
    sensitivity: str,
    verification_status: str,
    success: bool = True,
    error_message: str | None = None,
) -> EvidenceRecord:
    """Record evidence of filling a field."""
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=EVIDENCE_FIELD_FILLED,
        step_number=step,
        field_label=field_label,
        canonical_name=canonical_name,
        before_value=before_value,
        after_value=after_value,
        source=source,
        confidence=confidence,
        sensitivity=sensitivity,
        verification_status=verification_status,
        success=success,
        error_message=error_message,
    )
    return store.record(evidence)


def record_question_answer(
    store: EvidenceStore,
    run_id: str,
    step: int,
    question: str,
    answer: str,
    source: str,
    confidence: str,
    success: bool = True,
    error_message: str | None = None,
) -> EvidenceRecord:
    """Record evidence of answering a question."""
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=EVIDENCE_QUESTION_ANSWERED,
        step_number=step,
        field_label=question,
        after_value=answer,
        source=source,
        confidence=confidence,
        success=success,
        error_message=error_message,
    )
    return store.record(evidence)


def record_submission(
    store: EvidenceStore,
    run_id: str,
    step: int,
    success: bool,
    submission_url: str | None = None,
    confirmation_id: str | None = None,
    error_message: str | None = None,
) -> EvidenceRecord:
    """Record evidence of submission attempt."""
    evidence_type = (
        EVIDENCE_SUBMISSION_CONFIRMED if success
        else EVIDENCE_SUBMISSION_FAILED
    )
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=evidence_type,
        step_number=step,
        success=success,
        error_message=error_message,
        metadata={
            "submission_url": submission_url,
            "confirmation_id": confirmation_id,
        },
    )
    return store.record(evidence)


def record_error(
    store: EvidenceStore,
    run_id: str,
    step: int,
    error_message: str,
    field_label: str | None = None,
) -> EvidenceRecord:
    """Record evidence of an error."""
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=EVIDENCE_ERROR,
        step_number=step,
        field_label=field_label,
        success=False,
        error_message=error_message,
    )
    return store.record(evidence)


# ---------------------------------------------------------------------------
# Phase 16: file upload and advanced control evidence helpers
# ---------------------------------------------------------------------------


def record_file_upload(
    store: EvidenceStore,
    run_id: str,
    step: int,
    field_label: str,
    document_type: str,
    filename: str,
    content_type: str,
    success: bool,
    validation_result: str = "VALID",
    verification_result: str | None = None,
    error_message: str | None = None,
    page_identifier: str | None = None,
) -> EvidenceRecord:
    """Record evidence of a file upload attempt."""
    evidence_type = EVIDENCE_FILE_UPLOADED if success else EVIDENCE_FILE_UPLOAD_FAILED
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=evidence_type,
        step_number=step,
        field_label=field_label,
        after_value=filename,
        source="package",
        success=success,
        error_message=error_message,
        control_type="file",
        document_type=document_type,
        uploaded_filename=filename,
        validation_result=validation_result,
        verification_result=verification_result,
        page_identifier=page_identifier,
        metadata={"content_type": content_type},
    )
    return store.record(evidence)


def record_file_validation(
    store: EvidenceStore,
    run_id: str,
    step: int,
    field_label: str,
    document_type: str,
    filename: str,
    validation_result: str,
    error_message: str | None = None,
) -> EvidenceRecord:
    """Record evidence of file validation."""
    evidence_type = (
        EVIDENCE_FILE_VALIDATED if validation_result == "VALID"
        else EVIDENCE_FILE_VALIDATION_FAILED
    )
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=evidence_type,
        step_number=step,
        field_label=field_label,
        control_type="file",
        document_type=document_type,
        uploaded_filename=filename,
        validation_result=validation_result,
        success=validation_result == "VALID",
        error_message=error_message,
    )
    return store.record(evidence)


def record_advanced_field_fill(
    store: EvidenceStore,
    run_id: str,
    step: int,
    field_label: str,
    canonical_name: str,
    control_type: str,
    value: str,
    before_value: str | None = None,
    source: str = "profile",
    success: bool = True,
    page_identifier: str | None = None,
) -> EvidenceRecord:
    """Record evidence of an advanced field fill (checkbox, radio, multi-select, etc.)."""
    _TYPE_MAP = {
        "checkbox": EVIDENCE_CHECKBOX_TOGGLED,
        "radio": EVIDENCE_RADIO_SELECTED,
        "multi_select": EVIDENCE_MULTI_SELECT_CHANGED,
        "autocomplete": EVIDENCE_AUTOCOMPLETE_SELECTED,
        "date": EVIDENCE_DATE_FILLED,
        "currency": EVIDENCE_CURRENCY_FILLED,
    }
    evidence_type = _TYPE_MAP.get(control_type, EVIDENCE_FIELD_FILLED)
    evidence = EvidenceRecord(
        run_id=run_id,
        evidence_type=evidence_type,
        step_number=step,
        field_label=field_label,
        canonical_name=canonical_name,
        before_value=before_value,
        after_value=value,
        source=source,
        success=success,
        control_type=control_type,
        page_identifier=page_identifier,
    )
    return store.record(evidence)
