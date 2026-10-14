from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

OnboardingStep = Literal[
    "welcome", "identity", "personality", "memory_import", "memory_review", "first_chat", "refinements"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileIn(_Strict):
    display_name: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)


class Communication(_Strict):
    formality: Literal["casual", "balanced", "formal"] | None = None
    length: Literal["short", "medium", "long"] | None = None
    emoji: Literal["never", "sometimes", "often"] | None = None


class Appearance(_Strict):
    framing: Literal["close", "bust", "wide"] | None = None
    background: Literal["ivory", "wine", "maroon", "gold"] | None = None
    lighting: Literal["soft", "warm", "neutral"] | None = None


class TwinIn(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    about: str | None = Field(default=None, max_length=2000)
    communication: Communication | None = None
    appearance: Appearance | None = None


class PersonalityIn(_Strict):
    answers: dict[str, Any]


class ConsentIn(_Strict):
    version: str = Field(max_length=32)
