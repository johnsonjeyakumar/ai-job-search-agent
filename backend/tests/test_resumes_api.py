import pytest

from app.api.routes.resumes import get_file_storage
from app.storage.local import LocalFileStorage

VALID_RESUME = {
    "name": "Full Stack Resume",
    "target_role": "Full Stack Developer",
    "version": "v1",
}

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n%%EOF"


@pytest.fixture
def resume_client(client, tmp_path):
    """Client with storage pointed at a throwaway directory."""
    storage = LocalFileStorage(tmp_path / "resumes")
    client.app.dependency_overrides[get_file_storage] = lambda: storage
    yield client, storage
    client.app.dependency_overrides.pop(get_file_storage, None)


def _upload(client, *, name="resume.pdf", data=PDF_BYTES, ctype="application/pdf", **form_fields):
    fields = {**VALID_RESUME, **form_fields}
    return client.post(
        "/resumes",
        data=fields,
        files={"file": (name, data, ctype)},
    )


def test_resume_create_and_metadata(resume_client):
    client, storage = resume_client
    response = _upload(client)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Full Stack Resume"
    assert data["file_name"] == "resume.pdf"
    assert data["file_size"] == len(PDF_BYTES)
    assert data["content_type"] == "application/pdf"
    assert data["is_active"] is True
    assert "file_path" not in data


def test_resume_list_and_get(resume_client):
    client, _ = resume_client
    created = _upload(client).json()
    listed = client.get("/resumes")
    assert listed.status_code == 200
    assert [r["id"] for r in listed.json()] == [created["id"]]

    fetched = client.get(f"/resumes/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["target_role"] == "Full Stack Developer"
    assert "file_path" not in fetched.json()


def test_resume_get_missing_404(resume_client):
    client, _ = resume_client
    assert client.get("/resumes/999999").status_code == 404


def test_resume_update_metadata_and_active(resume_client):
    client, _ = resume_client
    created = _upload(client).json()
    updated = client.put(
        f"/resumes/{created['id']}",
        json={"name": "Backend Resume", "target_role": "Backend Developer", "is_active": True},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["name"] == "Backend Resume"
    assert body["target_role"] == "Backend Developer"
    assert body["is_active"] is True


def test_resume_only_one_active(resume_client):
    client, _ = resume_client
    first = _upload(client, name="a.pdf").json()
    second = _upload(client, name="b.pdf").json()
    assert first["is_active"] is True
    assert second["is_active"] is True
    assert client.get(f"/resumes/{first['id']}").json()["is_active"] is False


def test_resume_replace_file(resume_client):
    client, _ = resume_client
    created = _upload(client, data=PDF_BYTES).json()
    new_bytes = b"%PDF-1.7\nreplacement content\n%%EOF"
    replaced = client.post(
        f"/resumes/{created['id']}/file",
        files={"file": ("new.pdf", new_bytes, "application/pdf")},
    )
    assert replaced.status_code == 200
    body = replaced.json()
    assert body["file_size"] == len(new_bytes)
    assert body["file_name"] == "new.pdf"
    assert "file_path" not in body


def test_resume_delete_removes_row_and_file(resume_client):
    client, storage = resume_client
    created = _upload(client).json()
    response = client.delete(f"/resumes/{created['id']}")
    assert response.status_code == 204
    assert client.get(f"/resumes/{created['id']}").status_code == 404
    assert list(storage.root.glob("*")) == []


def test_resume_delete_missing_404(resume_client):
    client, _ = resume_client
    assert client.delete("/resumes/999999").status_code == 404


def test_resume_rejects_disallowed_extension(resume_client):
    client, _ = resume_client
    response = _upload(client, name="virus.exe", data=b"MZ", ctype="application/octet-stream")
    assert response.status_code == 422


def test_resume_rejects_fake_pdf(resume_client):
    client, _ = resume_client
    response = _upload(client, data=b"this is not a real pdf")
    assert response.status_code == 422


def test_resume_rejects_empty_file(resume_client):
    client, _ = resume_client
    response = _upload(client, data=b"")
    assert response.status_code == 422


def test_resume_oversized_file_rejected(resume_client):
    client, _ = resume_client
    big = b"%PDF-1.4" + b"x" * (10 * 1024 * 1024)
    response = _upload(client, data=big)
    assert response.status_code == 422


def test_resume_traversal_filename_sanitized(resume_client):
    client, _ = resume_client
    response = _upload(client, name="../../outside/resume.pdf")
    assert response.status_code == 200
    assert response.json()["file_name"] == "resume.pdf"


def test_resume_missing_file_422(resume_client):
    client, _ = resume_client
    response = client.post("/resumes", data=VALID_RESUME)
    assert response.status_code == 422
