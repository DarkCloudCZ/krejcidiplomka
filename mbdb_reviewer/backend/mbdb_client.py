"""MBDB REST API client for fetching biophysics metadata records."""
import requests
from typing import Dict, Any, List, Optional, Tuple
from fastapi import HTTPException
from config import MBDB_TOKEN, get_mbdb_base_url


def fetch_mbdb_record_detail(
    model: str,
    record_id: str,
    draft: bool,
    token: Optional[str] = None,
    environment: str = "production"
) -> Tuple[Dict[str, Any], str, bool]:
    """
    Download a single record (draft or published) from MBDB.
    If draft=True and draft fetch fails with 404, automatically falls back to published version.

    Args:
        model: MBDB model type (mst, bli, itc, spr)
        record_id: Record identifier
        draft: If True, fetch draft version (requires token)
        token: Optional token from frontend (overrides .env token)
        environment: "production" or "staging"

    Returns:
        Tuple of (record_data, source, fallback_used)
        - source: "draft" or "published"
        - fallback_used: True if draft was requested but published was returned
    """
    base_url = get_mbdb_base_url(environment)
    headers: Dict[str, str] = {}

    if draft:
        # Use provided token, or fall back to env token
        auth_token = token or MBDB_TOKEN
        if not auth_token:
            raise HTTPException(
                status_code=400,
                detail="MBDB token required for drafts. Please provide token or set MBDB_TOKEN in .env",
            )
        headers["Authorization"] = f"Bearer {auth_token}"
        url = f"{base_url}/records/{model}/{record_id}/draft"

        # Detailed logging for draft requests
        print(f"\n{'='*80}")
        print(f"🔍 DRAFT FETCH ATTEMPT:")
        print(f"   Environment: {environment}")
        print(f"   URL: {url}")
        print(f"   Token provided: {'Yes' if token else 'No (using .env)'}")
        print(f"   Token length: {len(auth_token) if auth_token else 0} chars")
        print(f"   Token preview: {auth_token[:20]}..." if auth_token and len(auth_token) > 20 else f"   Token: {auth_token}")
        print(f"{'='*80}\n")

        resp = requests.get(url, headers=headers, timeout=20)

        print(f"📡 RESPONSE FROM DRAFT ENDPOINT:")
        print(f"   Status: {resp.status_code}")
        print(f"   Reason: {resp.reason}")
        print(f"   Headers: {dict(resp.headers)}")

        # Handle different error responses
        if resp.status_code == 401:
            print(f"🚫 AUTHENTICATION FAILED (401 Unauthorized)")
            print(f"   The token was rejected by the server")
            print(f"   This usually means the token is invalid, expired, or for a different environment")
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed. Token is invalid or expired. Status: {resp.status_code}",
            )
        elif resp.status_code == 403:
            print(f"🚫 PERMISSION DENIED (403 Forbidden)")
            print(f"   The token is valid but doesn't have access to this draft")
            raise HTTPException(
                status_code=403,
                detail=f"Access forbidden. Token doesn't have permission to access this draft. Status: {resp.status_code}",
            )
        elif resp.status_code == 404:
            print(f"⚠️  Draft not found (404) - draft doesn't exist or isn't accessible with this token")
            print(f"   Falling back to published version...")
            # Try published version instead
            published_url = f"{base_url}/records/{model}/{record_id}"
            published_resp = requests.get(published_url, timeout=20)

            if published_resp.ok:
                print(f"✅ Successfully fetched published version as fallback")
                # Return published version with fallback indicator
                return published_resp.json(), "published", True
            else:
                # Neither draft nor published exists
                print(f"❌ Neither draft nor published version exists")
                raise HTTPException(
                    status_code=404,
                    detail=f"Record not found. Draft returned 404, published also not available.",
                )

        if not resp.ok:
            print(f"❌ Draft fetch failed with status {resp.status_code}: {resp.text[:200]}")
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"MBDB error {resp.status_code}: {resp.text}",
            )
        print(f"✅ Successfully fetched draft version for {model}/{record_id}")
        return resp.json(), "draft", False
    else:
        url = f"{base_url}/records/{model}/{record_id}"
        resp = requests.get(url, headers=headers, timeout=20)
        if not resp.ok:
            raise HTTPException(
                status_code=resp.status_code,
                detail=f"MBDB error {resp.status_code}: {resp.text}",
            )
        return resp.json(), "published", False


def fetch_mbdb_record_list(
    model: str,
    token: Optional[str] = None,
    environment: str = "production"
) -> List[Dict[str, Any]]:
    """
    Return first page of records for given model.

    Args:
        model: MBDB model type (mst, bli, itc, spr)
        token: Optional authentication token. If provided, may return draft records
               in addition to published records (depends on MBDB API behavior)
        environment: "production" or "staging"

    Returns:
        List of record hits
    """
    base_url = get_mbdb_base_url(environment)
    url = f"{base_url}/records/{model}/"
    headers: Dict[str, str] = {}

    # Add authentication if token provided
    if token:
        auth_token = token or MBDB_TOKEN
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
            print(f"🔑 Fetching {model} list WITH authentication token ({environment})")
    else:
        print(f"🔓 Fetching {model} list WITHOUT authentication ({environment}, public records only)")

    resp = requests.get(url, headers=headers, timeout=20)

    print(f"📊 LIST RESPONSE: Status {resp.status_code}, Records count: ", end="")

    if not resp.ok:
        print(f"ERROR")
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"MBDB list error {resp.status_code}: {resp.text}",
        )

    data = resp.json()
    hits = data.get("hits")
    if isinstance(hits, dict):
        hits_list = hits.get("hits", [])
    elif isinstance(hits, list):
        hits_list = hits
    else:
        hits_list = []

    if not isinstance(hits_list, list):
        hits_list = []

    print(f"{len(hits_list)}")

    # Log which records have is_draft flag if authenticated
    if token and hits_list:
        draft_records = [h for h in hits_list if h.get('is_draft', False)]
        published_records = [h for h in hits_list if h.get('is_published', False)]
        print(f"   Draft records: {len(draft_records)}, Published records: {len(published_records)}")
        if draft_records:
            print(f"   Draft IDs: {[r.get('id') for r in draft_records[:5]]}")

    return hits_list
