from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.errors import register_exception_handlers
from app.api.router import api_router
from app.config.settings import get_settings

settings = get_settings()


def _api_key_auth(request: Request) -> bool:
    """Validate API key when one is configured. Returns True if valid."""
    if not settings.api_key:
        return True
    auth = request.headers.get("authorization", "")
    x_api = request.headers.get("x-api-key", "")
    if auth.startswith("Bearer ") and auth[7:] == settings.api_key:
        return True
    if x_api == settings.api_key:
        return True
    return False


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path == "/health" or request.method == "OPTIONS":
            return await call_next(request)
        if not _api_key_auth(request):
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        return await call_next(request)

    app.include_router(api_router)
    register_exception_handlers(app)
    return app


app = create_app()
