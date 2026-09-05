from fastapi import APIRouter

from app.api.routes import (
    applications,
    health,
    jobs,
    preferences,
    profile,
    resumes,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(profile.router)
api_router.include_router(preferences.router)
api_router.include_router(resumes.router)
api_router.include_router(jobs.router)
api_router.include_router(applications.router)
