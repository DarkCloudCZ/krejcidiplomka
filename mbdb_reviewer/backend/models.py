"""Pydantic request models for the MBDB reviewer API."""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class FetchRecordRequest(BaseModel):
    """Request model for fetching MBDB records."""

    record_id: Optional[str] = None
    model: str = "mst"
    draft: bool = True
    token: Optional[str] = None
    environment: str = "production"


class ValidateRequest(BaseModel):
    """Request model for streamed validation."""

    record_json: Dict[str, Any]
    validators: List[str]
