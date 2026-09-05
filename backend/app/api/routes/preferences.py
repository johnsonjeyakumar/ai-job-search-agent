from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.preferences import PreferencesRead, PreferencesUpdate
from app.services import preferences_service, profile_service

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("", response_model=PreferencesRead)
def read_preferences(db: Session = Depends(get_db)) -> PreferencesRead:
    preferences = preferences_service.get_preferences(db)
    if preferences is None:
        return preferences_service.default_preferences_read()
    return preferences


@router.put("", response_model=PreferencesRead)
def update_preferences(
    payload: PreferencesUpdate, db: Session = Depends(get_db)
) -> PreferencesRead:
    profile = profile_service.get_profile(db)
    return preferences_service.upsert_preferences(
        db, payload, profile_id=profile.id if profile else None
    )
