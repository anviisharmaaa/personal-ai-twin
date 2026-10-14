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
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
