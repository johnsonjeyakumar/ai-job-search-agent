"""Safe file handling for application uploads (Phase 16).

Accepts files ONLY from the verified application package.  Validates file
existence, readability, extension, MIME type, size, ownership, and document
type before any upload attempt.

Safety invariants:
- Never recursively search arbitrary directories.
- Never choose the "closest" random file.
- Never upload browser downloads automatically.
- Never upload credentials/secrets.
- Never expose file contents in logs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Controlled vocabularies
# ---------------------------------------------------------------------------

DOCUMENT_TYPES = (
    "resume",
    "cover_letter",
    "portfolio",
    "certificate",
    "other",
)

FILE_VALIDATION_STATUSES = (
    "VALID",
    "MISSING",
    "INVALID_EXTENSION",
    "INVALID_MIME",
    "TOO_LARGE",
    "NOT_VERIFIED",
    "WRONG_DOCUMENT_TYPE",
    "AMBIGUOUS",
    "UPLOAD_FAILED",
    "UPLOAD_VERIFIED",
)

# Allowed extensions per document type (lowercase, with dot)
_ALLOWED_EXTENSIONS: dict[str, tuple[str, ...]] = {
    "resume": (".pdf", ".doc", ".docx", ".txt", ".rtf"),
    "cover_letter": (".pdf", ".doc", ".docx", ".txt"),
    "portfolio": (".pdf", ".doc", ".docx", ".txt", ".zip"),
    "certificate": (".pdf", ".jpg", ".jpeg", ".png"),
    "other": (".pdf", ".doc", ".docx", ".txt", ".png", ".jpg", ".jpeg"),
}

# Allowed MIME types per document type
_ALLOWED_MIMES: dict[str, tuple[str, ...]] = {
    "resume": (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/rtf",
    ),
    "cover_letter": (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    ),
    "portfolio": (
        "application/pdf",
        "application/zip",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
    ),
    "certificate": (
        "application/pdf",
        "image/jpeg",
        "image/png",
    ),
    "other": (
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "image/png",
        "image/jpeg",
    ),
}

# Default max file size: 10 MB
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class FileArtifact:
    """A verified file artifact from an application package."""

    file_path: str
    file_name: str
    content_type: str
    document_type: str  # resume | cover_letter | portfolio | certificate | other
    package_id: int | None = None
    verified: bool = False
    size_bytes: int | None = None


@dataclass
class FileValidationResult:
    """Result of validating a file for upload."""

    status: str  # FILE_VALIDATION_STATUSES
    file_path: str | None = None
    file_name: str | None = None
    document_type: str | None = None
    message: str = ""
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------

def validate_file_exists(file_path: str) -> FileValidationResult:
    """Check that a file exists and is readable."""
    if not file_path:
        return FileValidationResult(status="MISSING", message="No file path provided.")
    p = Path(file_path)
    if not p.exists():
        return FileValidationResult(
            status="MISSING",
            file_path=file_path,
            message=f"File not found: {file_path}",
        )
    if not p.is_file():
        return FileValidationResult(
            status="MISSING",
            file_path=file_path,
            message=f"Path is not a file: {file_path}",
        )
    if not os.access(file_path, os.R_OK):
        return FileValidationResult(
            status="MISSING",
            file_path=file_path,
            message=f"File is not readable: {file_path}",
        )
    return FileValidationResult(status="VALID", file_path=file_path)


def validate_file_extension(
    file_path: str,
    document_type: str = "other",
) -> FileValidationResult:
    """Check that the file extension is allowed for the document type."""
    if not file_path:
        return FileValidationResult(status="MISSING", message="No file path provided.")
    p = Path(file_path)
    ext = p.suffix.lower()
    allowed = _ALLOWED_EXTENSIONS.get(document_type, _ALLOWED_EXTENSIONS["other"])
    if ext not in allowed:
        return FileValidationResult(
            status="INVALID_EXTENSION",
            file_path=file_path,
            file_name=p.name,
            document_type=document_type,
            message=f"Extension '{ext}' not allowed for {document_type}. Allowed: {', '.join(allowed)}",
        )
    return FileValidationResult(status="VALID", file_path=file_path, file_name=p.name)


def validate_file_mime_type(
    content_type: str,
    document_type: str = "other",
) -> FileValidationResult:
    """Check that the MIME type is allowed for the document type."""
    if not content_type:
        return FileValidationResult(
            status="INVALID_MIME",
            message="No content type provided.",
        )
    allowed = _ALLOWED_MIMES.get(document_type, _ALLOWED_MIMES["other"])
    if content_type not in allowed:
        return FileValidationResult(
            status="INVALID_MIME",
            document_type=document_type,
            message=f"MIME type '{content_type}' not allowed for {document_type}.",
        )
    return FileValidationResult(status="VALID", document_type=document_type)


def validate_file_size(
    size_bytes: int,
    max_size: int = DEFAULT_MAX_FILE_SIZE,
) -> FileValidationResult:
    """Check that the file size is within limits."""
    if size_bytes <= 0:
        return FileValidationResult(
            status="MISSING",
            message="File is empty (0 bytes).",
        )
    if size_bytes > max_size:
        max_mb = max_size / (1024 * 1024)
        actual_mb = size_bytes / (1024 * 1024)
        return FileValidationResult(
            status="TOO_LARGE",
            message=f"File size {actual_mb:.1f} MB exceeds limit of {max_mb:.1f} MB.",
            details={"size_bytes": size_bytes, "max_bytes": max_size},
        )
    return FileValidationResult(status="VALID", details={"size_bytes": size_bytes})


def validate_file_ownership(
    file_path: str,
    package_id: int | None,
    expected_package_id: int | None,
) -> FileValidationResult:
    """Verify the file belongs to the expected application package."""
    if expected_package_id is not None and package_id != expected_package_id:
        return FileValidationResult(
            status="NOT_VERIFIED",
            file_path=file_path,
            message="File does not belong to the expected application package.",
        )
    return FileValidationResult(status="VALID", file_path=file_path)


def validate_file_for_upload(
    file_path: str,
    content_type: str,
    document_type: str,
    package_id: int | None = None,
    expected_package_id: int | None = None,
    size_bytes: int | None = None,
    max_file_size: int = DEFAULT_MAX_FILE_SIZE,
) -> FileValidationResult:
    """Run the full validation chain for a file upload.

    Returns the first failing validation, or VALID if all checks pass.
    """
    # 1. Existence
    result = validate_file_exists(file_path)
    if result.status != "VALID":
        return result

    # 2. Extension
    result = validate_file_extension(file_path, document_type)
    if result.status != "VALID":
        return result

    # 3. MIME type
    result = validate_file_mime_type(content_type, document_type)
    if result.status != "VALID":
        return result

    # 4. Size (if known)
    if size_bytes is not None:
        result = validate_file_size(size_bytes, max_file_size)
        if result.status != "VALID":
            return result

    # 5. Ownership
    result = validate_file_ownership(file_path, package_id, expected_package_id)
    if result.status != "VALID":
        return result

    return FileValidationResult(
        status="VALID",
        file_path=file_path,
        file_name=Path(file_path).name,
        document_type=document_type,
    )


def get_file_size(file_path: str) -> int | None:
    """Return file size in bytes, or None if inaccessible."""
    try:
        return os.path.getsize(file_path)
    except OSError:
        return None


def detect_document_type_from_label(label: str) -> str | None:
    """Map an upload field label to a canonical document type.

    Returns None if the label does not match any known document concept.
    """
    if not label:
        return None
    lbl = label.lower().strip()

    resume_keywords = ("resume", "cv", "curriculum vitae")
    cover_keywords = ("cover letter", "covering letter", "cover letter file")
    portfolio_keywords = ("portfolio", "work samples", "writing samples", "projects")
    cert_keywords = ("certificate", "certification", "credential", "license")

    for kw in resume_keywords:
        if kw in lbl:
            return "resume"
    for kw in cover_keywords:
        if kw in lbl:
            return "cover_letter"
    for kw in portfolio_keywords:
        if kw in lbl:
            return "portfolio"
    for kw in cert_keywords:
        if kw in lbl:
            return "certificate"
    return None
