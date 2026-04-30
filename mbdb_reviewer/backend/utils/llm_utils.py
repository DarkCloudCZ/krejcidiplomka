"""Utility functions for LLM client management."""

import random
import re
import time
from datetime import datetime, timezone
from threading import BoundedSemaphore
from typing import Any, Optional

from openai import OpenAI, RateLimitError

from config import (
    CHAT_AI_BASE_URL,
    CHAT_AI_MAX_PARALLEL_REQUESTS,
    CHAT_AI_RATE_LIMIT_BUFFER_SECONDS,
    CHAT_AI_RATE_LIMIT_RETRIES,
    CHAT_AI_TOKEN,
)

# Global client instance (singleton pattern)
_chat_client: Optional[OpenAI] = None
_chat_request_slots = BoundedSemaphore(CHAT_AI_MAX_PARALLEL_REQUESTS)
_RATE_LIMIT_RESET_RE = re.compile(r"Limit resets at:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) UTC")


def get_chat_ai_client() -> OpenAI:
    """Return a singleton OpenAI client for the Chat AI endpoint."""
    global _chat_client
    if _chat_client is None:
        if not CHAT_AI_TOKEN:
            raise RuntimeError("E_INFRA_API_TOKEN is not set in .env.")
        _chat_client = OpenAI(base_url=CHAT_AI_BASE_URL, api_key=CHAT_AI_TOKEN)
    return _chat_client


def get_chat_ai_parallel_limit() -> int:
    """Expose the local request cap used for Chat AI calls."""
    return CHAT_AI_MAX_PARALLEL_REQUESTS


def _is_rate_limit_error(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code == 429:
        return True
    return "429" in str(exc) and "rate limit" in str(exc).lower()


def _retry_delay_seconds(exc: Exception) -> Optional[float]:
    match = _RATE_LIMIT_RESET_RE.search(str(exc))
    if not match:
        return None

    reset_time = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return max(0.0, (reset_time - now).total_seconds())


def create_chat_completion(client: OpenAI, **kwargs: Any):
    """Execute one chat completion call under the shared concurrency cap."""

    last_exc: Optional[Exception] = None

    for attempt in range(CHAT_AI_RATE_LIMIT_RETRIES + 1):
        with _chat_request_slots:
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_exc = exc

        if last_exc is None or not _is_rate_limit_error(last_exc):
            raise last_exc  # type: ignore[misc]
        if attempt >= CHAT_AI_RATE_LIMIT_RETRIES:
            raise last_exc

        delay = _retry_delay_seconds(last_exc)
        if delay is None:
            delay = min(2 ** attempt, 8)

        delay += CHAT_AI_RATE_LIMIT_BUFFER_SECONDS + random.uniform(0.0, 0.25)
        print(
            f"Chat AI rate limit hit; retrying in {delay:.1f}s "
            f"(attempt {attempt + 1}/{CHAT_AI_RATE_LIMIT_RETRIES})"
        )
        time.sleep(delay)

    raise RuntimeError("Chat completion retry loop exited unexpectedly.")
