from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# "personality" is the stored id of the Character step (kept so existing progress and the DB check stay valid).
OnboardingStep = Literal[
    "welcome", "identity", "personality", "memory_import", "memory_review", "first_chat", "refinements"
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProfileIn(_Strict):
    display_name: str | None = Field(default=None, max_length=80)
    timezone: str | None = Field(default=None, max_length=64)


class Appearance(_Strict):
    framing: Literal["close", "bust", "wide"] | None = None
    background: Literal["ivory", "wine", "maroon", "gold"] | None = None
    lighting: Literal["soft", "warm", "neutral"] | None = None


class TwinIn(_Strict):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    about: str | None = Field(default=None, max_length=2000)
    appearance: Appearance | None = None


class CharacterIn(_Strict):
    # The user's own words. May be empty (clears it). base_version guards against overwriting a newer edit.
    description: str = Field(max_length=8000)
    base_version: int = Field(ge=0)


class AnalyzeIn(_Strict):
    version: int = Field(ge=1)


class ConsentIn(_Strict):
    version: str = Field(max_length=32)
