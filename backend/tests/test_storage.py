import pytest

from app.storage.local import LocalFileStorage, new_key
from app.storage.validation import (
    UploadValidationError,
    sanitize_filename,
    validate_upload,
)


class TestSanitizeFilename:
    def test_basename_only(self):
        assert sanitize_filename("../incoming/resume.pdf") == "resume.pdf"

    def test_windows_path_components_removed(self):
        assert sanitize_filename("C:\\Users\\me\\cv.docx") == "cv.docx"

    def test_invalid_characters_replaced(self):
        assert sanitize_filename("my:resume?.pdf") == "my_resume_.pdf"

    def test_rejects_dotdot(self):
        with pytest.raises(UploadValidationError):
            sanitize_filename("..")

    def test_rejects_empty(self):
        with pytest.raises(UploadValidationError):
            sanitize_filename("")


class TestValidateUpload:
    def test_valid_pdf(self):
        safe_name, ext = validate_upload(
            "resume.pdf", "application/pdf", b"%PDF-1.4\nfake", 1024 * 1024
        )
        assert safe_name == "resume.pdf"
        assert ext == ".pdf"

    def test_valid_docx(self):
        safe_name, _ = validate_upload(
            "resume.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            b"PK\x03\x04fake",
            1024 * 1024,
        )
        assert safe_name == "resume.docx"

    def test_rejects_disallowed_extension(self):
        with pytest.raises(UploadValidationError):
            validate_upload("resume.exe", "application/octet-stream", b"MZ", 1024)

    def test_rejects_fake_pdf(self):
        with pytest.raises(UploadValidationError):
            validate_upload("resume.pdf", "application/pdf", b"definitely not pdf", 1024)

    def test_rejects_empty(self):
        with pytest.raises(UploadValidationError):
            validate_upload("resume.pdf", "application/pdf", b"", 1024)

    def test_rejects_oversized(self):
        with pytest.raises(UploadValidationError):
            validate_upload("resume.pdf", "application/pdf", b"%PDF-1.4" * 1000, 10)

    def test_traversal_filename_is_sanitized_not_rejected(self):
        safe_name, _ = validate_upload(
            "../../etc/passwd.pdf", "application/pdf", b"%PDF-1.4", 1024
        )
        assert safe_name == "passwd.pdf"
        assert "/" not in safe_name


class TestLocalFileStorage:
    def test_save_load_delete_roundtrip(self, tmp_path):
        storage = LocalFileStorage(tmp_path / "uploads")
        key = new_key(".pdf")
        path = storage.save(b"%PDF-1.4", key)
        assert path.is_file()
        assert storage.load(key) == b"%PDF-1.4"
        storage.delete(key)
        assert not path.exists()

    def test_key_cannot_traverse(self, tmp_path):
        storage = LocalFileStorage(tmp_path / "uploads")
        with pytest.raises(ValueError):
            storage.save(b"x", "../escape.pdf")

    def test_new_keys_are_unique(self):
        assert new_key(".pdf") != new_key(".pdf")
        assert new_key(".pdf").endswith(".pdf")
