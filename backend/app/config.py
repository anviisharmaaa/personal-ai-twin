from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    supabase_url: str = ""
    # Public "publishable"/anon key. Requests are made *as the user* so RLS applies.
    supabase_publishable_key: str = ""
    # Only used if the project signs JWTs with the legacy shared secret (HS256).
    supabase_jwt_secret: str = ""
    # Reserved for later stages (workers, deletion). Never used for user-facing reads.
    supabase_service_role_key: str = ""
    openai_api_key: str = ""
    # Model used ONLY for character analysis. No default in code: the operator chooses it explicitly
    # (see .env.example) and nothing here ever switches models on its own.
    openai_character_model: str = ""
    # Deprecated name, read only so we can warn about it. It is never used for any call and never
    # falls back into the character model, so a future chat model setting cannot leak into this feature.
    openai_chat_model: str = ""
    # Kill switch for every external AI call (budget protection / incident response).
    ai_enabled: bool = True
    # Per-user cap on character analyses per rolling 24 hours (a UI limit alone cannot guarantee spend).
    analysis_daily_limit: int = 10
    analysis_timeout_seconds: float = 60.0
    analysis_max_output_tokens: int = 3000
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
