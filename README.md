# MBDB Review Tool

Diploma thesis project. Fetches metadata records from the [Molecular Biophysics Database (MBDB)](https://mbdb-data.org) and runs rule-based and LLM-powered validators to identify potential issues.

**Public version available at [krejcidiplomka.cz](https://krejcidiplomka.cz/)**

## Prerequisites

- Python 3.10+
- Node.js 18+
- An [e-INFRA CZ Chat AI](https://docs.cerit.io/en/docs/ai-as-a-service/chat-ai) API token
- (Optional) An MBDB token to access draft records

## Setup

### Backend

```bash
cd mbdb_reviewer/backend

python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # Linux/macOS

pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your tokens:

```
E_INFRA_API_TOKEN=your_chat_ai_token
MBDB_TOKEN=your_mbdb_token        # optional
CHAT_AI_MODEL=deepseek-v3.2-thinking
```

Start the server:

```bash
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd mbdb_reviewer/frontend/mbdb_reviewer_frontend
npm install
npm run dev
```

App runs at **http://localhost:5173**

### Quick start (Windows)

```bash
start-dev.bat
```

## Architecture

```
mbdb_reviewer/
├── backend/
│   ├── main.py           # FastAPI app entry point
│   ├── config.py         # Configuration and env vars
│   ├── mbdb_client.py    # MBDB REST API client
│   ├── models.py         # Pydantic request models
│   ├── routes/           # API route handlers
│   ├── validators/       # Rule-based and AI validators
│   └── utils/            # Shared utilities
└── frontend/
    └── mbdb_reviewer_frontend/
        └── src/
            ├── App.tsx   # Main React component
            └── App.css   # Styles
```
