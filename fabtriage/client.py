"""API clients. Both backends speak the OpenAI protocol.

meta:    Meta Model API (Muse Spark 1.3, SAM 3.1), Responses API.   MODEL_API_KEY
baseten: Muse Spark Open on Baseten, Chat Completions API.          BASETEN_API_KEY
"""

from __future__ import annotations

import os
from pathlib import Path

BACKENDS = {
    "meta": {
        "key": "MODEL_API_KEY",
        "base_url_env": "MODEL_API_BASE_URL",
        "base_url": "https://api.meta.ai/v1",
        "model": "muse-spark-1.3",
        "api": "responses",
    },
    "baseten": {
        "key": "BASETEN_API_KEY",
        "base_url_env": "BASETEN_BASE_URL",
        "base_url": "https://inference.baseten.co/v1",
        "model": "meta-models/muse-spark-open-1026",
        "api": "chat",
    },
}


def load_env(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from .env into the environment (existing values win)."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def has_key(backend: str) -> bool:
    return bool(os.environ.get(BACKENDS[backend]["key"]))


def make_client(backend: str = "meta"):
    from openai import OpenAI

    spec = BACKENDS[backend]
    key = os.environ.get(spec["key"], "")
    if not key:
        raise RuntimeError(f"{spec['key']} is not set: add it to .env")
    return OpenAI(
        api_key=key,
        base_url=os.environ.get(spec["base_url_env"]) or spec["base_url"],
        max_retries=4,
        timeout=180,
    )


def model_for(backend: str) -> str:
    return os.environ.get("AGENT_MODEL") or BACKENDS[backend]["model"]
