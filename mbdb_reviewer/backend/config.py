"""Configuration for the MBDB reviewer backend."""
import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# MBDB API Configuration
MBDB_BASE_URL = os.getenv("MBDB_BASE_URL", "https://mbdb-data.org/api")
MBDB_PRODUCTION_URL = "https://mbdb-data.org/api"
MBDB_STAGING_URL = "https://stage.mbdb-data.org/api"
MBDB_TOKEN = os.getenv("MBDB_TOKEN") or os.getenv("MBDB_DEFAULT_TOKEN", "")

# Chat AI (LLM) Configuration
# API Endpoint: https://llm.ai.e-infra.cz/v1/ (OpenAI-compatible)
# Docs: https://docs.cerit.io/en/docs/ai-as-a-service/chat-ai
CHAT_AI_BASE_URL = os.getenv("CHAT_AI_BASE_URL", "https://llm.ai.e-infra.cz/v1/")
CHAT_AI_TOKEN = os.getenv("E_INFRA_API_TOKEN")
CHAT_AI_MODEL = os.getenv("CHAT_AI_MODEL", "deepseek-v3.2-thinking")

# Runtime 429 responses from the provider report max_parallel_requests=4,
# so local defaults stay below that ceiling.
CHAT_AI_MAX_PARALLEL_REQUESTS = max(1, int(os.getenv("CHAT_AI_MAX_PARALLEL_REQUESTS", "3")))
CHAT_AI_RATE_LIMIT_RETRIES = max(0, int(os.getenv("CHAT_AI_RATE_LIMIT_RETRIES", "2")))
CHAT_AI_RATE_LIMIT_BUFFER_SECONDS = max(
    0.0, float(os.getenv("CHAT_AI_RATE_LIMIT_BUFFER_SECONDS", "1.0"))
)
AI_VALIDATOR_MAX_WORKERS = max(
    1,
    min(
        CHAT_AI_MAX_PARALLEL_REQUESTS,
        int(os.getenv("AI_VALIDATOR_MAX_WORKERS", str(CHAT_AI_MAX_PARALLEL_REQUESTS))),
    ),
)
TEXT_LINT_MAX_WORKERS = max(
    1,
    min(
        CHAT_AI_MAX_PARALLEL_REQUESTS,
        int(os.getenv("TEXT_LINT_MAX_WORKERS", str(CHAT_AI_MAX_PARALLEL_REQUESTS))),
    ),
)

# Validation Configuration
CHUNK_SIZE = 50  # Max items per LLM request for text linting

# CORS Configuration
CORS_ORIGINS = ["http://localhost:5173", "http://localhost:3000"]


def get_mbdb_base_url(environment: str = "production") -> str:
    if environment == "staging":
        return MBDB_STAGING_URL
    if environment == "production":
        return MBDB_PRODUCTION_URL
    return MBDB_BASE_URL
