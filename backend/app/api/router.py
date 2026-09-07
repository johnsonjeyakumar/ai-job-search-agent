from fastapi import APIRouter

from app.api.routes import (
    analytics,
    applications,
    companies,
    health,
    interview,
    jobs,
    preferences,
    profile,
    resumes,
    tracking,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(profile.router)
api_router.include_router(preferences.router)
api_router.include_router(resumes.router)
api_router.include_router(jobs.router)
api_router.include_router(companies.router)
api_router.include_router(applications.router)
api_router.include_router(tracking.router)
api_router.include_router(interview.router)
api_router.include_router(analytics.router)
