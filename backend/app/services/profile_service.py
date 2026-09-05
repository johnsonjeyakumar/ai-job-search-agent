from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.profile import Profile
from app.schemas.profile import ProfileCreate

_SKILL_CATEGORY_FIELDS = [
    "skills_programming",
    "skills_frameworks",
    "skills_databases",
    "skills_tools",
    "skills_other",
]


def _merge_skills(data: ProfileCreate) -> list[str]:
    """Aggregate categorized skills (plus any legacy flat list) into one list."""
    combined: list[str] = []
    for field in _SKILL_CATEGORY_FIELDS:
        combined.extend(getattr(data, field) or [])
    combined.extend(data.skills or [])
    return _dedupe(combined)


def _merge_skills_from_profile(profile: Profile) -> list[str]:
    """Recompute the aggregate from the currently stored category fields."""
    combined: list[str] = []
    for field in _SKILL_CATEGORY_FIELDS:
        combined.extend(getattr(profile, field) or [])
    combined.extend(profile.skills or [])
    return _dedupe(combined)


def _dedupe(combined: list[str]) -> list[str]:
    seen: set[str] = set()
    merged: list[str] = []
    for skill in combined:
        normalized = skill.strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            merged.append(normalized)
    return merged


def _derive_location(data: ProfileCreate) -> str | None:
    city = (data.city or "").strip()
    state = (data.state or "").strip()
    country = (data.country or "").strip()
    parts = [part for part in (city, state, country) if part]
    if parts:
        return ", ".join(parts)
    return (data.location or "").strip() or None


def _derive_location_from_profile(profile: Profile) -> str | None:
    city = (profile.city or "").strip()
    state = (profile.state or "").strip()
    country = (profile.country or "").strip()
    parts = [part for part in (city, state, country) if part]
    if parts:
        return ", ".join(parts)
    return (profile.location or "").strip() or None


def get_profile(db: Session) -> Profile | None:
    return db.scalar(select(Profile).order_by(Profile.id).limit(1))


def _apply_data(profile: Profile, data: ProfileCreate) -> Profile:
    # mode="json" serializes AnyUrl/lists for storage as plain strings.
    values = data.model_dump(mode="json")
    values["skills"] = _merge_skills(data)
    values["location"] = _derive_location(data)
    for field, value in values.items():
        setattr(profile, field, value)
    return profile


def create_profile(db: Session, data: ProfileCreate) -> Profile:
    profile = Profile()
    db.add(_apply_data(profile, data))
    db.commit()
    db.refresh(profile)
    return profile


def update_profile(db: Session, profile: Profile, data: ProfileCreate) -> Profile:
    db.add(_apply_data(profile, data))
    db.commit()
    db.refresh(profile)
    return profile


def update_profile_partial(db: Session, profile: Profile, data) -> Profile:
    """Apply only the fields the client actually provided, then re-derive
    helper aggregates (skills, location) from the updated state."""
    values = data.model_dump(exclude_unset=True, mode="json")
    for field, value in values.items():
        setattr(profile, field, value)
    profile.location = _derive_location_from_profile(profile)
    profile.skills = _merge_skills_from_profile(profile)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def upsert_profile(db: Session, data: ProfileCreate) -> Profile:
    existing = get_profile(db)
    if existing is None:
        return create_profile(db, data)
    return update_profile(db, existing, data)
