"""Application execution analytics (Phase 20).

Tracks execution metrics, success rates, field mapping accuracy,
and provides insights for improving the application process.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class ExecutionMetrics:
    """Metrics for a single execution run."""

    run_id: str = ""
    total_fields: int = 0
    mapped_fields: int = 0
    filled_fields: int = 0
    skipped_fields: int = 0
    failed_fields: int = 0
    total_questions: int = 0
    answered_questions: int = 0
    skipped_questions: int = 0
    unknown_questions: int = 0
    submission_attempted: bool = False
    submission_succeeded: bool = False
    submission_failed: bool = False
    duration_seconds: float = 0.0
    human_approvals_requested: int = 0
    human_approvals_granted: int = 0
    errors_recovered: int = 0
    checkpoints_created: int = 0
    started_at: str = ""
    completed_at: str = ""

    @property
    def mapping_accuracy(self) -> float:
        """Percentage of fields that were mapped."""
        if self.total_fields == 0:
            return 0.0
        return (self.mapped_fields / self.total_fields) * 100

    @property
    def fill_rate(self) -> float:
        """Percentage of mapped fields that were filled."""
        if self.mapped_fields == 0:
            return 0.0
        return (self.filled_fields / self.mapped_fields) * 100

    @property
    def question_answer_rate(self) -> float:
        """Percentage of questions that were answered."""
        if self.total_questions == 0:
            return 0.0
        return (self.answered_questions / self.total_questions) * 100

    @property
    def success_rate(self) -> float:
        """Whether the submission succeeded."""
        if not self.submission_attempted:
            return 0.0
        return 100.0 if self.submission_succeeded else 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "total_fields": self.total_fields,
            "mapped_fields": self.mapped_fields,
            "filled_fields": self.filled_fields,
            "skipped_fields": self.skipped_fields,
            "failed_fields": self.failed_fields,
            "total_questions": self.total_questions,
            "answered_questions": self.answered_questions,
            "skipped_questions": self.skipped_questions,
            "unknown_questions": self.unknown_questions,
            "submission_attempted": self.submission_attempted,
            "submission_succeeded": self.submission_succeeded,
            "submission_failed": self.submission_failed,
            "duration_seconds": self.duration_seconds,
            "human_approvals_requested": self.human_approvals_requested,
            "human_approvals_granted": self.human_approvals_granted,
            "errors_recovered": self.errors_recovered,
            "checkpoints_created": self.checkpoints_created,
            "mapping_accuracy": self.mapping_accuracy,
            "fill_rate": self.fill_rate,
            "question_answer_rate": self.question_answer_rate,
            "success_rate": self.success_rate,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


@dataclass
class AnalyticsStore:
    """Stores and computes analytics across runs."""

    metrics: dict[str, ExecutionMetrics] = field(default_factory=dict)
    field_mapping_stats: dict[str, dict] = field(default_factory=dict)
    platform_stats: dict[str, dict] = field(default_factory=dict)

    def get_or_create(self, run_id: str) -> ExecutionMetrics:
        """Get or create metrics for a run."""
        if run_id not in self.metrics:
            self.metrics[run_id] = ExecutionMetrics(
                run_id=run_id,
                started_at=datetime.now(timezone.utc).isoformat(),
            )
        return self.metrics[run_id]

    def record_field_mapping(
        self,
        canonical: str,
        method: str,
        confidence: str,
        success: bool,
    ) -> None:
        """Record a field mapping for analytics."""
        if canonical not in self.field_mapping_stats:
            self.field_mapping_stats[canonical] = {
                "total": 0,
                "success": 0,
                "methods": {},
                "confidences": {},
            }

        stats = self.field_mapping_stats[canonical]
        stats["total"] += 1
        if success:
            stats["success"] += 1

        stats["methods"][method] = stats["methods"].get(method, 0) + 1
        stats["confidences"][confidence] = (
            stats["confidences"].get(confidence, 0) + 1
        )

    def record_platform_run(
        self,
        platform: str,
        success: bool,
        duration: float,
    ) -> None:
        """Record a platform run for analytics."""
        if platform not in self.platform_stats:
            self.platform_stats[platform] = {
                "total_runs": 0,
                "successful_runs": 0,
                "total_duration": 0.0,
            }

        stats = self.platform_stats[platform]
        stats["total_runs"] += 1
        if success:
            stats["successful_runs"] += 1
        stats["total_duration"] += duration

    def get_overall_stats(self) -> dict:
        """Get overall analytics across all runs."""
        total_runs = len(self.metrics)
        successful_runs = sum(
            1 for m in self.metrics.values() if m.submission_succeeded
        )
        total_fields = sum(m.total_fields for m in self.metrics.values())
        mapped_fields = sum(m.mapped_fields for m in self.metrics.values())
        filled_fields = sum(m.filled_fields for m in self.metrics.values())

        return {
            "total_runs": total_runs,
            "successful_runs": successful_runs,
            "success_rate": (
                (successful_runs / total_runs * 100) if total_runs > 0 else 0
            ),
            "total_fields": total_fields,
            "mapped_fields": mapped_fields,
            "mapping_accuracy": (
                (mapped_fields / total_fields * 100) if total_fields > 0 else 0
            ),
            "fill_rate": (
                (filled_fields / mapped_fields * 100) if mapped_fields > 0 else 0
            ),
        }

    def get_field_mapping_accuracy(self) -> dict[str, float]:
        """Get mapping accuracy by field type."""
        result = {}
        for canonical, stats in self.field_mapping_stats.items():
            if stats["total"] > 0:
                result[canonical] = (
                    stats["success"] / stats["total"] * 100
                )
        return result

    def get_platform_performance(self) -> dict[str, dict]:
        """Get performance by platform."""
        result = {}
        for platform, stats in self.platform_stats.items():
            if stats["total_runs"] > 0:
                result[platform] = {
                    "runs": stats["total_runs"],
                    "success_rate": (
                        stats["successful_runs"] / stats["total_runs"] * 100
                    ),
                    "avg_duration": (
                        stats["total_duration"] / stats["total_runs"]
                    ),
                }
        return result
