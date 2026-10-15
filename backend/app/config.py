from functools import lru_cache

from pydantic import Field
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
    # Which AI provider character analysis uses: "nvidia", "ollama" (local), "openai", "mock" (sample output, no
    # network; refused when APP_ENV=production) or empty (AI off). Explicit on purpose: there is no automatic fallback.
    ai_provider: str = ""
    # NVIDIA NIM hosted API (free development endpoint). Character model has no default in code.
    nvidia_api_key: str = ""
    nvidia_character_model: str = ""
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    # "guided_json" (NIM's documented structured output) or "prompt" (schema in prompt, strict validation after).
    nvidia_json_mode: str = "guided_json"
    # Output budget for NVIDIA only (the shared ANALYSIS_MAX_OUTPUT_TOKENS still governs OpenAI). Hard-bounded so it
    # cannot be raised enough to hide a runaway-reasoning problem: a full profile needs well under 4096 tokens.
    nvidia_max_output_tokens: int = Field(default=4096, ge=512, le=8192)
    # Ollama: a model served on this machine through its OpenAI-compatible API. No API key. The endpoint must be a
    # loopback address unless OLLAMA_ALLOW_REMOTE=true is set deliberately (see app.providers.ollama_endpoint_ok).
    ollama_base_url: str = "http://localhost:11434/v1"
    ollama_character_model: str = ""
    ollama_allow_remote: bool = False
    # "schema" sends response_format=json_schema; "prompt" relies on the schema in the prompt only.
    ollama_json_mode: str = "schema"
    # Sent as reasoning_effort ("none" turns thinking off on models that support it). Empty = do not send.
    ollama_reasoning_effort: str = "none"
    ollama_max_output_tokens: int = Field(default=4096, ge=512, le=8192)
    # Local inference can be slow on CPU, so this is separate from the cloud timeout.
    ollama_timeout_seconds: float = Field(default=600.0, ge=10.0, le=1800.0)
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
    # ---- Chat (Phase 4). Provider is the same explicit AI_PROVIDER; chat is allowed only for local Ollama (and the
    # labelled sample generator). All limits are configurable and hard-bounded.
    # Messages and characters of earlier history sent to the model, newest first; older turns are dropped (and the UI
    # is told), never silently pretended to be remembered.
    chat_context_messages: int = Field(default=24, ge=2, le=100)
    chat_context_chars: int = Field(default=12000, ge=1000, le=60000)
    # Ceiling on one chat reply (Ollama options.num_predict). A safety limit, not a target: the prompt asks for short
    # replies. Separate from analysis_/ollama_/learning_ output limits, which are unchanged. Raise it if you want longer
    # replies; a reply that reaches it is stored as "incomplete", never as complete.
    chat_max_output_tokens: int = Field(default=128, ge=16, le=4096)
    # Chat talks to Ollama's NATIVE /api/chat (derived from OLLAMA_BASE_URL) so that thinking can be switched off with
    # the documented `think` flag. False = no reasoning phase for ordinary character chat.
    chat_think: bool = False
    chat_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    # Context window to request per chat call (options.num_ctx). 0 = leave it to the Ollama server's own setting.
    chat_num_ctx: int = Field(default=0, ge=0, le=131072)
    # How long Ollama keeps the model loaded after a reply, so the next message does not pay the load time again.
    chat_keep_alive: str = Field(default="30m", pattern=r"^(-1|0|\d+(\.\d+)?(ms|s|m|h))$")
    chat_max_user_chars: int = Field(default=4000, ge=100, le=20000)
    # A cold local model must load and read the prompt before its first token, so this is generous but bounded.
    chat_first_token_timeout_seconds: float = Field(default=300.0, ge=5.0, le=1800.0)
    chat_total_timeout_seconds: float = Field(default=900.0, ge=10.0, le=3600.0)
    chat_messages_per_hour: int = Field(default=120, ge=1, le=5000)
    chat_memory_limit: int = Field(default=8, ge=0, le=30)
    # Local-model jobs (chat replies, character analysis, learning review) that may run at once. 1 on purpose:
    # concurrent runs on one CPU/GPU make every one of them slower.
    local_model_concurrency: int = Field(default=1, ge=1, le=4)
    # Conversational learning: how many of the newest user messages one review reads.
    learning_review_messages: int = Field(default=40, ge=2, le=200)
    learning_max_candidates: int = Field(default=8, ge=1, le=20)
    learning_reviews_per_hour: int = Field(default=10, ge=1, le=100)
    learning_timeout_seconds: float = Field(default=600.0, ge=10.0, le=1800.0)
    learning_max_output_tokens: int = Field(default=1536, ge=256, le=4096)
    cors_origins: str = "http://localhost:5173"

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
