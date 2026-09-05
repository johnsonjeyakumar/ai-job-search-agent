from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.preferences import Preferences
from app.schemas.preferences import PreferencesRead, PreferencesUpdate


def get_preferences(db: Session) -> Preferences | None:
    return db.scalar(select(Preferences).order_by(Preferences.id).limit(1))


def upsert_preferences(
    db: Session, data: PreferencesUpdate, profile_id: int | None = None
) -> Preferences:
    preferences = get_preferences(db)

    # Start from friendly defaults, overlay any previously saved values,
    # then overlay what the client actually provided.
    merged = PreferencesUpdate().model_dump()
    if preferences is not None:
        merged.update(
            {key: getattr(preferences, key) for key in merged if hasattr(preferences, key)}
        )
    merged.update(data.model_dump(exclude_unset=True))
    values = {key: value for key, value in merged.items() if hasattr(Preferences, key)}

    if preferences is None:
        preferences = Preferences(**values, profile_id=profile_id)
        db.add(preferences)
    else:
        for key, value in values.items():
            setattr(preferences, key, value)
        if profile_id is not None:
            preferences.profile_id = profile_id
    db.commit()
    db.refresh(preferences)
    return preferences


def default_preferences_read() -> PreferencesRead:
    """Defaults used until the user saves preferences for the first time."""
    return PreferencesRead(**PreferencesUpdate().model_dump())
