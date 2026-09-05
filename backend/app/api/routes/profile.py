from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.schemas.profile import ProfileCreate, ProfileRead, ProfileUpdate
from app.services import profile_service

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileRead)
def read_profile(db: Session = Depends(get_db)) -> ProfileRead:
    profile = profile_service.get_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Create one with POST /profile.",
        )
    return profile


@router.post("", response_model=ProfileRead)
def create_or_update_profile(
    payload: ProfileCreate, db: Session = Depends(get_db)
) -> ProfileRead:
    """Create the profile if none exists, otherwise update it (onboarding save)."""
    return profile_service.upsert_profile(db, payload)


@router.put("", response_model=ProfileRead)
def update_profile(
    payload: ProfileUpdate, db: Session = Depends(get_db)
) -> ProfileRead:
    """Apply only the provided fields to the existing profile (partial update)."""
    profile = profile_service.get_profile(db)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found. Create one with POST /profile.",
        )
    return profile_service.update_profile_partial(db, profile, payload)
