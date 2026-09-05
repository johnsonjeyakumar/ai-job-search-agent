from app.schemas.preferences import (
    DEFAULT_EMPLOYMENT_TYPES,
    DEFAULT_EXPERIENCE_LEVELS,
    DEFAULT_PREFERRED_LOCATIONS,
    DEFAULT_REMOTE_TYPES,
    DEFAULT_TARGET_ROLES,
    PreferencesUpdate,
)

VALID_PREFERENCES = {
    "preferred_locations": ["Chennai", "Bangalore", "Remote - India"],
    "experience_levels": ["Fresher"],
    "target_roles": ["Full Stack Developer", "Frontend Developer"],
    "remote_types": ["remote"],
    "employment_types": ["full_time"],
    "min_match_score": 75,
    "salary_min": 300000,
    "salary_max": 900000,
    "posted_within_days": 7,
    "include_keywords": ["React"],
    "exclude_keywords": ["night shift"],
}


def test_preferences_defaults_when_never_saved(client):
    response = client.get("/preferences")
    assert response.status_code == 200
    data = response.json()
    assert data["preferred_locations"] == DEFAULT_PREFERRED_LOCATIONS
    assert data["experience_levels"] == DEFAULT_EXPERIENCE_LEVELS
    assert data["target_roles"] == DEFAULT_TARGET_ROLES
    assert data["remote_types"] == DEFAULT_REMOTE_TYPES
    assert data["employment_types"] == DEFAULT_EMPLOYMENT_TYPES
    assert data["min_match_score"] == 60
    assert data["posted_within_days"] == 30


def test_preferences_save_and_persist(client):
    first = client.put("/preferences", json=VALID_PREFERENCES)
    assert first.status_code == 200
    assert first.json()["min_match_score"] == 75

    fetched = client.get("/preferences")
    assert fetched.status_code == 200
    data = fetched.json()
    assert data["preferred_locations"] == VALID_PREFERENCES["preferred_locations"]
    assert data["include_keywords"] == ["React"]
    assert data["exclude_keywords"] == ["night shift"]


def test_preferences_update_not_duplicate(client):
    first = client.put("/preferences", json=VALID_PREFERENCES).json()
    second = client.put(
        "/preferences", json={**VALID_PREFERENCES, "min_match_score": 90}
    ).json()
    assert second["id"] == first["id"]
    assert client.get("/preferences").json()["min_match_score"] == 90


def test_preferences_min_match_score_out_of_range(client):
    payload = {**VALID_PREFERENCES, "min_match_score": 150}
    response = client.put("/preferences", json=payload)
    assert response.status_code == 422


def test_preferences_partial_body_preserves_saved_values(client):
    client.put("/preferences", json=VALID_PREFERENCES)
    response = client.put("/preferences", json={"min_match_score": 85})
    assert response.status_code == 200
    data = response.json()
    assert data["min_match_score"] == 85
    assert data["preferred_locations"] == VALID_PREFERENCES["preferred_locations"]
    assert data["target_roles"] == VALID_PREFERENCES["target_roles"]


def test_preferences_schema_defaults():
    prefs = PreferencesUpdate()
    assert prefs.min_match_score == 60
    assert prefs.salary_min is None
    assert prefs.posted_within_days == 30
