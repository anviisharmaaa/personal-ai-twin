"""Read-only check of what is ACTUALLY running on this computer. Makes no analysis request and prints no secrets.

    python -m scripts.check_local [--backend http://localhost:8000]

Reports: (1) the provider the RUNNING backend says it uses (/ready), (2) the provider your backend/.env selects,
(3) whether Ollama answers and which models are installed, and (4) whether those agree. Nothing is downloaded.
"""
from __future__ import annotations

import argparse
import sys

import httpx

from app.config import get_settings
from app.providers import active_provider, ollama_endpoint_ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="http://localhost:8000")
    args = ap.parse_args()
    s = get_settings()
    problems = 0
    env_provider = active_provider(s) or "none"
    print(f".env selects provider: {env_provider}   (AI_PROVIDER={s.ai_provider or '(empty)'})")

    running = None
    try:
        r = httpx.get(args.backend.rstrip("/") + "/ready", timeout=5)
        j = r.json()
        running = j.get("ai_provider")
        print(f"running backend at {args.backend} reports: provider={running} configured={j.get('configured')}")
        for w in j.get("warnings", []):
            print(f"  warning: {w}")
        if running != env_provider:
            problems += 1
            print("  MISMATCH: the running backend was started before .env changed, or reads another env file. Restart it.")
    except (httpx.HTTPError, ValueError) as exc:
        problems += 1
        print(f"running backend at {args.backend}: NOT reachable ({type(exc).__name__}). Start it, then re-run.")

    if env_provider == "ollama" or s.ollama_character_model:
        root = s.ollama_base_url.rstrip("/").removesuffix("/v1")
        print(f"ollama endpoint {s.ollama_base_url}: local-only check passes = {ollama_endpoint_ok(s)}")
        try:
            names = [m.get("name") for m in httpx.get(root + "/api/tags", timeout=5).json().get("models", [])]
            print(f"  Ollama is running. Installed models: {names or 'none'}")
            want = s.ollama_character_model
            if want not in names and f"{want}:latest" not in names:
                problems += 1
                print(f"  OLLAMA_CHARACTER_MODEL={want!r} is NOT installed (nothing will be downloaded for you).")
            else:
                print(f"  model {want!r} is installed.")
        except (httpx.HTTPError, ValueError) as exc:
            problems += 1
            print(f"  Ollama NOT reachable ({type(exc).__name__}). Start it with: ollama serve")
    print("RESULT:", "consistent" if not problems else f"{problems} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
