VALID_PROFILE = {
    "name": "Test User",
    "email": "test@example.com",
    "location": "Chennai",
    "skills": ["Python", "React"],
    "preferred_roles": ["Backend Developer"],
    "preferred_locations": ["Chennai", "Remote India"],
    "experience_level": "fresher",
}


def test_profile_not_found_first(client):
    response = client.get("/profile")
    assert response.status_code == 404


def test_profile_create(client):
    response = client.post("/profile", json=VALID_PROFILE)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Test User"
    assert data["email"] == "test@example.com"
    assert data["skills"] == ["Python", "React"]


def test_profile_read_after_create(client):
    client.post("/profile", json=VALID_PROFILE)
    response = client.get("/profile")
    assert response.status_code == 200
    assert response.json()["location"] == "Chennai"


def test_profile_upsert_updates_existing(client):
    first = client.post("/profile", json=VALID_PROFILE).json()
    second = client.post(
        "/profile", json={**VALID_PROFILE, "location": "Madurai"}
    ).json()
    assert second["id"] == first["id"]
    assert second["location"] == "Madurai"


def test_profile_validation_missing_name(client):
    response = client.post("/profile", json={"email": "test@example.com"})
    assert response.status_code == 422


def test_profile_validation_bad_email(client):
    response = client.post("/profile", json={"name": "Test", "email": "not-an-email"})
    assert response.status_code == 422


def test_profile_validation_bad_graduation_year(client):
    response = client.post(
        "/profile",
        json={"name": "Test", "email": "t@e.com", "graduation_year": 1800},
    )
    assert response.status_code == 422


def test_profile_put_404_when_missing(client):
    response = client.put("/profile", json=VALID_PROFILE)
    assert response.status_code == 404


def test_profile_put_updates_existing(client):
    created = client.post("/profile", json=VALID_PROFILE).json()
    updated = client.put(
        "/profile", json={**VALID_PROFILE, "email": "new@example.com"}
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == created["id"]
    assert body["email"] == "new@example.com"


def test_profile_put_partial_preserves_other_fields(client):
    client.post("/profile", json=VALID_PROFILE)
    partial = client.put("/profile", json={"notice_period": "30 days"})
    assert partial.status_code == 200
    body = partial.json()
    assert body["notice_period"] == "30 days"
    assert body["name"] == "Test User"
    assert body["email"] == "test@example.com"
    assert body["preferred_roles"] == ["Backend Developer"]


def test_profile_put_partial_derives_aggregates(client):
    created = client.post("/profile", json={**VALID_PROFILE, "location": "Chennai"}).json()
    assert created["skills"] == ["Python", "React"]
    updated = client.put("/profile", json={"skills_programming": ["Python", "Go"]}).json()
    assert updated["skills"] == ["Python", "Go", "React"]
    located = client.put("/profile", json={"city": "Madurai", "state": "Tamil Nadu"}).json()
    assert located["location"] == "Madurai, Tamil Nadu"


def test_profile_skills_aggregation_and_location(client):
    payload = {
        **VALID_PROFILE,
        "city": "Chennai",
        "state": "Tamil Nadu",
        "country": "India",
        "skills_programming": ["Python", "python", "Java"],
        "skills_frameworks": ["React", "FastAPI"],
        "skills_databases": ["PostgreSQL"],
        "skills_tools": ["Docker", "Docker"],
        "skills_other": ["Teamwork"],
    }
    response = client.post("/profile", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["location"] == "Chennai, Tamil Nadu, India"
    assert data["skills"] == [
        "Python",
        "Java",
        "React",
        "FastAPI",
        "PostgreSQL",
        "Docker",
        "Teamwork",
    ]


def test_profile_validation_bad_urls(client):
    response = client.post(
        "/profile",
        json={
            **VALID_PROFILE,
            "linkedin_url": "not-a-url",
            "github_url": "also-not-a-url",
            "portfolio_url": "nope",
        },
    )
    assert response.status_code == 422
