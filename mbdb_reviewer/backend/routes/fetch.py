"""Routes for fetching MBDB records."""
from fastapi import APIRouter
from models import FetchRecordRequest
from mbdb_client import fetch_mbdb_record_detail, fetch_mbdb_record_list

router = APIRouter()


@router.post("/api/fetch-record")
def api_fetch_record(req: FetchRecordRequest):
    """Return one record detail or a list of records."""
    record_id = (req.record_id or "").strip()
    if record_id:
        record, source, fallback_used = fetch_mbdb_record_detail(
            model=req.model,
            record_id=record_id,
            draft=req.draft,
            token=req.token,
            environment=req.environment,
        )
        return {
            "mode": "detail",
            "record": record,
            "source": source,
            "fallback_used": fallback_used,
        }
    else:
        hits_list = fetch_mbdb_record_list(req.model, token=req.token, environment=req.environment)
        return {"mode": "list", "hits": hits_list}
