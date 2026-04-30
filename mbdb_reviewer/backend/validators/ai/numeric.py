"""
Numeric Validator (AI-based)

Validates numeric values for plausible ranges using LLM.
Uses pre-extraction to prevent path hallucination.
Includes technique-specific context for better validation.
"""

import json
from typing import Dict, Any, List
from openai import OpenAI

from utils.json_utils import iter_numeric_nodes, build_numeric_line_map, parse_llm_json_response
from utils.llm_utils import create_chat_completion, get_chat_ai_client
from config import CHAT_AI_MODEL


def _build_numeric_validation_prompt(numeric_nodes: List[Dict], technique: str = "", instrument: str = "") -> str:
    """Build the prompt for numeric range validation."""

    # Build technique-specific context if available
    technique_context = ""
    if technique or instrument:
        technique_context = f"""
EXPERIMENT CONTEXT:
- Technique: {technique or 'Not specified'}
- Instrument: {instrument or 'Not specified'}

TECHNIQUE-SPECIFIC RANGES (use these instead of generic ranges when applicable):
- BLI (Bio-layer interferometry): Shaking speed up to 1000-1500 RPM is normal (Octet instruments)
- SPR (Surface plasmon resonance): Flow rates typically 5-100 uL/min
- MST (Microscale thermophoresis): LED power 20-100%, IR laser power 20-80%
- ITC (Isothermal titration calorimetry): Stirring speed typically 100-750 RPM (instrument-dependent, use "warning" not "error" for unusual values)
"""

    return f"""You are validating numeric values from a molecular biophysics experiment record (MBDB).
{technique_context}
Below is a list of numeric values with their paths, units, and context. Check each for:
- Values outside typical experimental ranges
- Zero or negative values where they should be positive
- Extreme values that might be typos (e.g., pH of 74 instead of 7.4)

DOMAIN KNOWLEDGE:
- pH: typically 0-14
- Temperature (Celsius): typically -80 to 150 for lab experiments
- Temperature (Kelvin): typically 193 to 423
- Concentrations: should be positive (zero is suspicious unless intentional control)
- Percentages: typically 0-100
- Time values: should be positive
- Molecular weights (Da/kDa): should be positive, proteins typically 1-500 kDa

RULES:
1. ONLY report values from the list below - do NOT invent paths
2. Copy the "path" field EXACTLY from the input
3. Be conservative - only flag clearly suspicious values
4. Consider the "context_key" to understand what the value represents
5. Consider the "unit" when evaluating if a value is reasonable
6. Apply technique-specific ranges when the experiment context is provided

Input values:
{json.dumps(numeric_nodes, ensure_ascii=False, indent=2)}

Return ONLY a JSON array. Each object must have:
- "path": exact path from input (copy exactly!)
- "severity": "warning" or "error"
- "message": short description of the problem
- "value": the numeric value being flagged
- "unit": the unit (or null if none)
- "expected_range": what typical values might be (e.g., "0-14 for pH")

If all values look reasonable, return []. No markdown, just JSON."""


def _process_numeric_chunk(client: OpenAI, chunk: List[Dict], technique: str = "", instrument: str = "") -> List[Dict]:
    """Process a single chunk of numeric nodes through the LLM."""
    prompt = _build_numeric_validation_prompt(chunk, technique, instrument)

    completion = create_chat_completion(
        client,
        model=CHAT_AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    content = completion.choices[0].message.content.strip()
    return parse_llm_json_response(content)


def run_numeric_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Extract numeric values and validate ranges using LLM.
    Uses pre-extraction to prevent path hallucination.
    Includes technique context for technique-specific range validation.
    """
    client = get_chat_ai_client()

    # Extract technique context for technique-specific range validation
    metadata = record_json.get("metadata", {})
    gp = metadata.get("general_parameters", {})
    technique = gp.get("technique", {})
    technique_name = technique.get("name", "") if isinstance(technique, dict) else str(technique)

    instrument = gp.get("instrument", {})
    instrument_name = instrument.get("name", "") or instrument.get("title", {}).get("en", "")

    numeric_nodes = list(iter_numeric_nodes(record_json))

    if not numeric_nodes:
        return []

    # Build set of valid paths for post-validation
    valid_paths = {node["path"] for node in numeric_nodes}

    # Prepare pretty-printed JSON for line number lookup
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    # Build path-to-line map BEFORE processing (tracks occurrence order)
    path_to_line = build_numeric_line_map(json_pretty, numeric_nodes)

    # Process in chunks (use larger chunks for numeric - simpler data)
    chunk_size = 100
    all_issues: List[Dict] = []
    for i in range(0, len(numeric_nodes), chunk_size):
        chunk = numeric_nodes[i:i + chunk_size]
        chunk_issues = _process_numeric_chunk(client, chunk, technique_name, instrument_name)

        # Post-validate: only keep issues with valid paths
        for issue in chunk_issues:
            if issue.get("path") in valid_paths:
                issue["validator"] = "numeric"
                issue["category"] = "range"
                # Add line number from pre-computed map
                issue["line"] = path_to_line.get(issue["path"])
                all_issues.append(issue)

    return all_issues
