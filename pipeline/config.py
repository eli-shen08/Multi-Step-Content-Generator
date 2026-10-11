"""Provider settings and the raw chat call. Any OpenAI-compatible endpoint works (Groq, Gemini, Ollama)."""
import os
import time
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

from pipeline.events import emit

load_dotenv()


@dataclass(frozen=True)
class Settings:
    api_key: str = os.getenv("LLAMA_API_KEY", "")
    base_url: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
    model: str = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    moderation_model: str = os.getenv("MODERATION_MODEL", "openai/gpt-oss-20b")
    # gpt-oss models think before answering; "low" keeps each call around a second.
    reasoning_effort: str = os.getenv("REASONING_EFFORT", "low")
    max_idea_chars: int = 500


settings = Settings()

# Groq's free tier allows 8K tokens/min *per model*, so each workload gets its own model:
# writing stages on the strongest model, brief + review on qwen, outline + moderation on gpt-oss-20b
# (gpt-oss-safeguard-20b is capped at 2K tokens/min, too low for checking every output).
# Set LLM_MODEL_<STAGE> (e.g. LLM_MODEL_DRAFT) to override one stage; LLM_MODEL is the fallback.
STAGE_MODELS = {
    "understand": "qwen/qwen3.8-27b",
    "outline": "openai/gpt-oss-20b",
    "draft": "openai/gpt-oss-120b",
    "improve": "openai/gpt-oss-120b",
    "final": "openai/gpt-oss-120b",
    "review": "qwen/qwen3.8-27b",
    "re-review": "qwen/qwen3.8-27b",
}


def model_for(stage: str) -> str:
    stage = stage.split("#")[0]  # "improve#2" is a later round of "improve"
    key = f"LLM_MODEL_{stage.upper().replace('-', '_')}"
    return os.getenv(key) or STAGE_MODELS.get(stage) or settings.model


def reasoning_args(model: str) -> dict:
    """reasoning_effort only exists on gpt-oss models; other models reject it."""
    return {"reasoning_effort": settings.reasoning_effort} if "gpt-oss" in model else {}

MAX_RATE_LIMIT_WAITS = 5


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    if not settings.api_key:
        raise RuntimeError("Set LLAMA_API_KEY in .env")
    # Retries handled in chat() so rate-limit waits are visible instead of a silent pause.
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0)


def chat(**kwargs):
    """chat.completions.create with visible waiting on 429 (Groq free tier: 30 requests/min)."""
    client = get_client()
    for attempt in range(MAX_RATE_LIMIT_WAITS + 1):
        try:
            return client.chat.completions.create(**kwargs)
        except RateLimitError as exc:
            if attempt == MAX_RATE_LIMIT_WAITS:
                raise
            wait = float(exc.response.headers.get("retry-after", 10))
            emit("wait", model=kwargs["model"], seconds=wait)
            time.sleep(wait)
