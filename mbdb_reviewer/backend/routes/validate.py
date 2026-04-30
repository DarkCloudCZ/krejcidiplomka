"""Streaming routes for validating MBDB records."""

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from config import AI_VALIDATOR_MAX_WORKERS
from models import ValidateRequest
from validators.ai import (
    run_ai_text_lint_parallel,
    run_chem_env_name_validation,
    run_measurement_name_validation,
    run_numeric_validation,
    run_semantic_coherence_validation,
)
from validators.rules import (
    run_data_analysis_refs_validation,
    run_date_validation,
    run_entity_usage_validation,
    run_external_id_validation,
    run_placeholder_validation,
    run_required_fields_validation,
    run_result_plausibility_validation,
    run_sequence_content_validation,
    run_sequence_mw_validation,
    run_unit_consistency_validation,
    run_whitespace_validation,
)

router = APIRouter()

ValidatorFn = Callable[[Dict[str, Any]], List[Dict[str, Any]]]


def _run_text_validation(record_json: Dict[str, Any]) -> List[Dict[str, Any]]:
    issues = run_ai_text_lint_parallel(record_json)
    for issue in issues:
        issue.setdefault("validator", "text")
    return issues


AI_VALIDATORS: Dict[str, ValidatorFn] = {
    "text": _run_text_validation,
    "numeric": run_numeric_validation,
    "measurement_name": run_measurement_name_validation,
    "semantic_coherence": run_semantic_coherence_validation,
    "chem_env_name": run_chem_env_name_validation,
}

RULE_VALIDATORS: Dict[str, ValidatorFn] = {
    "required_fields": run_required_fields_validation,
    "date_consistency": run_date_validation,
    "data_analysis_refs": run_data_analysis_refs_validation,
    "entity_usage": run_entity_usage_validation,
    "unit_consistency": run_unit_consistency_validation,
    "result_plausibility": run_result_plausibility_validation,
    "external_ids": run_external_id_validation,
    "whitespace": run_whitespace_validation,
    "placeholder_values": run_placeholder_validation,
    "sequence_content": run_sequence_content_validation,
    "sequence_mw": run_sequence_mw_validation,
}


def _run_validator(
    validator_id: str,
    record_json: Dict[str, Any],
    validators: Dict[str, ValidatorFn],
) -> List[Dict[str, Any]]:
    issues = validators[validator_id](record_json)
    for issue in issues:
        issue.setdefault("validator", validator_id)
    return issues


@router.post("/api/validate-stream")
def api_validate_stream(req: ValidateRequest):
    """Stream validation results as each validator completes."""

    def generate():
        selected_rule = [validator_id for validator_id in req.validators if validator_id in RULE_VALIDATORS]
        selected_ai = [validator_id for validator_id in req.validators if validator_id in AI_VALIDATORS]

        for validator_id in selected_rule:
            try:
                issues = _run_validator(validator_id, req.record_json, RULE_VALIDATORS)
                yield f"data: {json.dumps({'validator': validator_id, 'issues': issues})}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'validator': validator_id, 'error': str(exc)})}\n\n"

        if selected_ai:
            max_workers = min(len(selected_ai), AI_VALIDATOR_MAX_WORKERS)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(_run_validator, validator_id, req.record_json, AI_VALIDATORS): validator_id
                    for validator_id in selected_ai
                }

                for future in as_completed(futures):
                    validator_id = futures[future]
                    try:
                        issues = future.result()
                        yield f"data: {json.dumps({'validator': validator_id, 'issues': issues})}\n\n"
                    except Exception as exc:
                        yield f"data: {json.dumps({'validator': validator_id, 'error': str(exc)})}\n\n"

        yield f"data: {json.dumps({'done': True})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )
