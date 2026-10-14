from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routes import router
from app.supabase_rest import SupabaseError


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Madhuora API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_list,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )
    app.include_router(router)

    @app.exception_handler(SupabaseError)
    async def supabase_error(_: Request, exc: SupabaseError) -> JSONResponse:
        # Never forward upstream bodies (could contain internals).
        if exc.status_code in (401, 403):
            return JSONResponse({"detail": "Invalid or expired session."}, status_code=401)
        if exc.status_code == 409:
            return JSONResponse({"detail": "Conflict."}, status_code=409)
        return JSONResponse({"detail": "Data service error. Please try again."}, status_code=502)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, object]:
        # Reports configuration presence only; never values.
        return {
            "status": "ok",
            "configured": {
                "supabase": bool(settings.supabase_url and settings.supabase_publishable_key),
                "openai": bool(settings.openai_api_key),
            },
        }

    return app


app = create_app()
