"""
Measurement Name Validator (AI-based)

Checks if measurement names match their actual content using LLM.
Only flags contradictions, not missing information.
Processes measurements in chunks of 20 to cover all measurements.
"""

import json
from typing import Dict, Any, List

from utils.json_utils import parse_llm_json_response
from utils.llm_utils import create_chat_completion, get_chat_ai_client
from config import CHAT_AI_MODEL

MEASUREMENT_CHUNK_SIZE = 20


def _build_prompt(measurement_data: List[Dict]) -> str:
    return f"""You are validating measurement names against their actual content in a molecular biophysics experiment.

IMPORTANT: ONLY flag when the name contains information that CONTRADICTS the actual data.

DO NOT flag:
- Names that don't mention concentrations (that's perfectly acceptable)
- Generic names like "sample 1", "rep 1", "measurement 1", "EL222-DNA (rep 1)"
- Names that simply omit details - missing info is NOT an error
- Names that don't include all entities or concentrations

ONLY flag actual contradictions:
- Name explicitly states "130 µM" but actual concentration is 65 µM (WRONG VALUE)
- Name mentions entity "BSA" that isn't present in ligands, targets, or analytes (WRONG ENTITY)
- Name claims "rep 3" but the measurement position is clearly 1 (WRONG REPLICATE)

Note: Entities may appear in ligands, targets, OR analytes — check ALL of these before flagging.
Note: Buffer components mentioned in the name (e.g., "MOPS", "PBS", "Tris") often come from the chemical_environment field, not from entities. Do NOT flag buffer/condition mentions as missing entities.

If the name is vague or generic, that is ACCEPTABLE - do not flag it.

Data to validate:
{json.dumps(measurement_data, ensure_ascii=False, indent=2)}

Return ONLY a JSON array of issues found. Each object must have:
- "index": the measurement index (as given in the data above)
- "severity": "warning"
- "message": description of the CONTRADICTION (not missing info)

If no contradictions found, return []. No markdown, just JSON."""


def _process_chunk(client, chunk_data: List[Dict], measurements: List[Dict]) -> List[Dict]:
    """Run one LLM call for a chunk and return formatted issues."""
    try:
        completion = create_chat_completion(
            client,
            model=CHAT_AI_MODEL,
            messages=[{"role": "user", "content": _build_prompt(chunk_data)}],
            temperature=0.1,
        )
        content = completion.choices[0].message.content.strip()
        llm_issues = parse_llm_json_response(content)
    except Exception:
        return []

    issues = []
    for issue in llm_issues:
        idx = issue.get("index", 0)
        if 0 <= idx < len(measurements):
            issues.append({
                "path": f"metadata.method_specific_parameters.measurements[{idx}].name",
                "severity": issue.get("severity", "warning"),
                "category": "cross_field",
                "message": issue.get("message", "Name may not match content"),
                "validator": "measurement_name",
                "value": measurements[idx].get("name", ""),
            })
    return issues


def run_measurement_name_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    AI-based validation: Check measurement names match their content.
    Uses LLM to parse free-text names and compare to structured data.
    Processes all measurements in chunks of 20.
    """
    client = get_chat_ai_client()
    msp = record_json.get("metadata", {}).get("method_specific_parameters", {})
    measurements = msp.get("measurements", [])

    if not measurements:
        return []

    all_issues: List[Dict] = []

    for chunk_start in range(0, len(measurements), MEASUREMENT_CHUNK_SIZE):
        chunk = measurements[chunk_start:chunk_start + MEASUREMENT_CHUNK_SIZE]
        chunk_data = []
        for local_idx, m in enumerate(chunk):
            abs_idx = chunk_start + local_idx
            sample = m.get("sample", {})
            entry = {
                "index": abs_idx,
                "name": m.get("name", ""),
                "ligands": [
                    {"name": l.get("entity", {}).get("name"), "conc": l.get("concentration", {})}
                    for l in sample.get("ligands", [])
                ],
                "targets": [
                    {"name": t.get("entity", {}).get("name"), "conc": t.get("concentration", {})}
                    for t in sample.get("targets", [])
                ],
                "analytes": [
                    {"name": a.get("entity", {}).get("name"), "conc": a.get("concentration", {})}
                    for a in sample.get("analytes", [])
                ],
            }
            # ITC-specific: sample_in_cell / sample_in_syringe
            for sample_key in ("sample_in_cell", "sample_in_syringe"):
                itc_sample = m.get(sample_key, {})
                itc_entities = [
                    {"name": e.get("entity", {}).get("name"), "conc": e.get("concentration", {})}
                    for container in ("targets", "ligands")
                    for e in itc_sample.get(container, [])
                ]
                if itc_entities:
                    entry.setdefault("ligands", []).extend(itc_entities)
            # Chemical environment name (buffer info often appears in measurement names)
            chem_env_name = sample.get("chemical_environment", {}).get("name", "")
            if not chem_env_name:
                for sample_key in ("sample_in_cell", "sample_in_syringe"):
                    chem_env_name = m.get(sample_key, {}).get("chemical_environment", {}).get("name", "")
                    if chem_env_name:
                        break
            if chem_env_name:
                entry["chemical_environment"] = chem_env_name
            chunk_data.append(entry)
        all_issues.extend(_process_chunk(client, chunk_data, measurements))

    return all_issues
