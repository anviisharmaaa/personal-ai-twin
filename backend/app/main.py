from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.character_routes import router as character_router
from app.config import get_settings
from app.providers import active_provider, ollama_endpoint_ok, provider_ready
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
    app.include_router(character_router)

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
        warnings: list[str] = []
        if settings.openai_chat_model and not settings.openai_character_model:
            warnings.append("OPENAI_CHAT_MODEL is not used for character analysis. Set OPENAI_CHARACTER_MODEL.")
        chosen = settings.ai_provider.strip().lower()
        if chosen and not active_provider(settings):
            warnings.append("AI_PROVIDER is not valid (use nvidia, ollama, openai or mock; "
                            "mock is refused in production).")
        if chosen == "ollama" and not ollama_endpoint_ok(settings):
            warnings.append("OLLAMA_BASE_URL is not a local address, so Ollama is disabled. Use "
                            "http://localhost:11434/v1 (a remote Ollama needs OLLAMA_ALLOW_REMOTE=true).")
        if not chosen and (settings.openai_api_key or settings.nvidia_api_key):
            warnings.append("An AI key is set but AI_PROVIDER is empty, so AI analysis is off. Set AI_PROVIDER.")
        return {
            "status": "ok",
            "warnings": warnings,
            "ai_provider": active_provider(settings) or "none",
            "configured": {
                "supabase": bool(settings.supabase_url and settings.supabase_publishable_key),
                "ai": provider_ready(settings),
            },
        }

    return app


app = create_app()
