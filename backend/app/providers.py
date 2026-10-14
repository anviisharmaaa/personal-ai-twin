"""Provider selection for character analysis.

AI_PROVIDER is explicit: "nvidia", "openai", "mock", or empty (= AI off). There is NO fallback from one
provider to another. If the chosen provider fails, the user sees an honest error and the last good
profile is kept.
"""

from typing import Any

import httpx

from app.character import (
    OUTPUT_JSON_SCHEMA,
    SYSTEM_PROMPT,
    AnalysisResult,
    CharacterProfile,
    OpenAIAnalyzer,
)
from app.config import Settings

CONSENT_BASE = "2026-10-v3"
PROVIDERS = ("nvidia", "openai", "mock")


def active_provider(s: Settings) -> str:
    """The configured provider id, or "" when none/unknown. "mock" is refused in production."""
    p = s.ai_provider.strip().lower()
    if p not in PROVIDERS or (p == "mock" and s.app_env.lower() == "production"):
        return ""
    return p


def consent_version(s: Settings) -> str:
    """Consent is tied to the provider: changing provider changes the version, so users must re-consent."""
    return f"{CONSENT_BASE}-{active_provider(s) or 'none'}"


def provider_info(s: Settings) -> dict[str, Any]:
    """What the UI shows in consent text and notices. Single source of truth for provider disclosure."""
    p = active_provider(s)
    if p == "nvidia":
        return {
            "id": "nvidia", "label": "NVIDIA", "external": True, "development_only": True,
            "disclosure": [
                "The character description you write is sent from Madhuora's server to NVIDIA's hosted API "
                "(NVIDIA NIM at build.nvidia.com), which runs outside India.",
                "This is a free development service. NVIDIA's API Trial Terms say it is for testing and evaluation, "
                "that NVIDIA may monitor content, and that submitted and generated content may be used to improve "
                "NVIDIA products and AI models. They also say it is not meant for personal, health or payment data.",
                "While this provider is active, please use fictional or non-sensitive descriptions only.",
            ],
        }
    if p == "openai":
        return {
            "id": "openai", "label": "OpenAI", "external": True, "development_only": False,
            "disclosure": [
                "The character description you write is sent from Madhuora's server to OpenAI's API, "
                "which processes data outside India.",
            ],
        }
    if p == "mock":
        return {
            "id": "mock", "label": "Sample (no AI)", "external": False, "development_only": True,
            "disclosure": [
                "This server is in sample mode. No AI model is used and nothing you write leaves Madhuora. "
                "Interpretations shown are fixed samples, not a reading of your description.",
            ],
        }
    return {
        "id": "none", "label": "None", "external": False, "development_only": False,
        "disclosure": ["No AI provider is configured on this server, so no AI analysis can run."],
    }


class NullAnalyzer:
    """Used when no provider is configured. Always reports 'not configured'; never calls anything."""

    provider = ""

    @property
    def configured(self) -> bool:
        return False

    async def analyze(self, description: str) -> AnalysisResult:  # pragma: no cover - route stops earlier
        raise NotImplementedError


class NvidiaAnalyzer(OpenAIAnalyzer):
    """NVIDIA NIM hosted API (OpenAI-compatible Chat Completions).

    Endpoint and Bearer auth are from NVIDIA's API docs. Structured output uses NIM's documented
    `nvext.guided_json`. Because hosted endpoints differ, `json_mode="prompt"` is the safest equivalent:
    the schema goes in the prompt and the reply is validated strictly (invalid replies are rejected,
    never repaired). `max_tokens` is the parameter NVIDIA's docs show.

    Reasoning is switched OFF for this task. Nemotron 3 Super reasons by default, and on a first live run its
    reasoning consumed the whole token budget, so no profile came back (finish_reason=length). NVIDIA's model
    card documents `chat_template_kwargs: {"enable_thinking": false}` for this (it does not document
    `reasoning_effort`, so that field is not sent). A character interpretation is extraction from given text,
    which does not need a reasoning trace. Truncation is still detected and reported, never parsed.
    """

    PROVIDER = "nvidia"

    def __init__(self, api_key: str, model: str, timeout_s: float, max_output_tokens: int,
                 base_url: str = "https://integrate.api.nvidia.com/v1", json_mode: str = "guided_json",
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(api_key, model, timeout_s, max_output_tokens, transport)
        self.URL = base_url.rstrip("/") + "/chat/completions"
        self._mode = json_mode

    def _payload(self, description: str) -> dict[str, Any]:
        import json

        system = SYSTEM_PROMPT
        payload: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_out,
            "temperature": 0.2,
            "stream": False,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        if self._mode == "guided_json":
            payload["nvext"] = {"guided_json": OUTPUT_JSON_SCHEMA}
        else:
            system += "\n\nThe JSON must match this JSON Schema exactly:\n" + json.dumps(OUTPUT_JSON_SCHEMA)
        payload["messages"] = [
            {"role": "system", "content": system},
            {"role": "user", "content": f"<description>\n{description}\n</description>"},
        ]
        return payload


# Fixed, obviously-generic sample. It never reads or repeats the user's description.
_MOCK = {
    "summary": "SAMPLE ONLY: no AI model read your description. This fixed example shows how an interpretation "
               "will look once a real provider is switched on.",
    "core_traits": [{"text": "Example trait: warm with people they know well", "basis": "stated"}],
    "speaking_style": [{"text": "Example: short, plain sentences", "basis": "inferred"}],
    "typical_expressions": [],
    "context_tendencies": [{"context": "Example situation: meeting someone new",
                            "tendency": "Example tendency: quieter and more careful", "basis": "inferred",
                            "evidence": "(sample)"}],
    "uncertainties": ["Everything on this page is a fixed sample, not an interpretation of your text."],
}


class MockAnalyzer:
    """Sample provider for UI development. No network, no cost, and its output is labelled as a sample."""

    provider = "mock"

    @property
    def configured(self) -> bool:
        return True

    async def analyze(self, description: str) -> AnalysisResult:
        return AnalysisResult(CharacterProfile.model_validate(_MOCK), "sample-fixture", 0, 0, 1, provider="mock")


def build_analyzer(s: Settings) -> Any:
    p = active_provider(s)
    if p == "nvidia":
        return NvidiaAnalyzer(s.nvidia_api_key, s.nvidia_character_model, s.analysis_timeout_seconds,
                              s.nvidia_max_output_tokens, s.nvidia_base_url, s.nvidia_json_mode)
    if p == "openai":
        return OpenAIAnalyzer(s.openai_api_key, s.openai_character_model, s.analysis_timeout_seconds,
                              s.analysis_max_output_tokens)
    if p == "mock":
        return MockAnalyzer()
    return NullAnalyzer()


def provider_model(s: Settings) -> str | None:
    return {"nvidia": s.nvidia_character_model, "openai": s.openai_character_model,
            "mock": "sample-fixture"}.get(active_provider(s)) or None


def provider_ready(s: Settings) -> bool:
    return bool(build_analyzer(s).configured)
