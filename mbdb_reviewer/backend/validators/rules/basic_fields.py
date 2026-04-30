"""
Basic field validation rules.

This module contains validators for basic field requirements and formats.

Validators:
- Required fields validation: Validates essential fields are present
- External ID format validation: Validates ORCID, UniProt, PDB, InChI formats
- Whitespace validation: Validates no leading/trailing whitespace in key fields
- Placeholder validation: Detects placeholder values like -1
"""

import json
import re
from typing import Any, Dict, List
from utils.json_utils import find_line_for_path_and_value, iter_numeric_nodes


# ============== REQUIRED FIELDS VALIDATION (Deterministic) ==============

def run_required_fields_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check that essential fields are present.
    Fully deterministic - no LLM needed, zero hallucinations.
    """
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)
    metadata = record_json.get("metadata", {})
    gp = metadata.get("general_parameters", {})

    issues = []

    # Check record title
    title = gp.get("record_information", {}).get("title")
    if not title or not title.strip():
        issues.append({
            "path": "metadata.general_parameters.record_information.title",
            "severity": "error",
            "category": "missing_field",
            "message": "Record title is missing or empty",
            "validator": "required_fields",
            "line": find_line_for_path_and_value(json_pretty, "record_information", "")
        })

    # Check entities of interest
    entities = gp.get("entities_of_interest", [])
    if not entities:
        issues.append({
            "path": "metadata.general_parameters.entities_of_interest",
            "severity": "error",
            "category": "missing_field",
            "message": "No entities of interest defined",
            "validator": "required_fields",
            "line": find_line_for_path_and_value(json_pretty, "entities_of_interest", "")
        })

    # Check chemical environments
    chem_envs = gp.get("chemical_environments", [])
    if not chem_envs:
        issues.append({
            "path": "metadata.general_parameters.chemical_environments",
            "severity": "warning",
            "category": "missing_field",
            "message": "No chemical environments defined",
            "validator": "required_fields",
            "line": find_line_for_path_and_value(json_pretty, "chemical_environments", "")
        })

    # Check results
    results = gp.get("results", [])
    if not results:
        issues.append({
            "path": "metadata.general_parameters.results",
            "severity": "warning",
            "category": "missing_field",
            "message": "No results defined (may be work in progress)",
            "validator": "required_fields",
            "line": find_line_for_path_and_value(json_pretty, "results", "")
        })

    # Check depositor
    depositor = gp.get("depositors", {}).get("depositor")
    if not depositor:
        issues.append({
            "path": "metadata.general_parameters.depositors.depositor",
            "severity": "warning",
            "category": "missing_field",
            "message": "Depositor information is missing",
            "validator": "required_fields",
            "line": find_line_for_path_and_value(json_pretty, "depositor", "")
        })

    return issues


# ============== EXTERNAL ID FORMAT VALIDATION (Deterministic) ==============

# Regex patterns for external identifier formats
EXTERNAL_ID_PATTERNS = {
    # ORCID: 16 digits with hyphens, last char can be X (checksum)
    # Valid: orcid:0000-0002-8564-8644
    # Invalid: orcid:https://orcid.org/0000-0002-8564-8644
    "orcid": (
        r"^orcid:\d{4}-\d{4}-\d{4}-\d{3}[\dX]$",
        "ORCID should be 'orcid:XXXX-XXXX-XXXX-XXXX' (no URL prefix)"
    ),
    # InChI Key: 27 uppercase letters in 14-10-1 pattern, NO space after prefix
    # Valid: inchikey:FAPWRFPIFSIZLT-UHFFFAOYSA-M
    # Invalid: inchikey: FAPWRFPIFSIZLT-UHFFFAOYSA-M (space after colon)
    "inchikey": (
        r"^inchikey:[A-Z]{14}-[A-Z]{10}-[A-Z]$",
        "InChI key should be 'inchikey:XXXXXXXXXXXXXX-XXXXXXXXXX-X' (no space after colon)"
    ),
    # UniProt: 6 or 10 alphanumeric characters
    # Valid: uniprot:Q2NB98, uniprot:A0A0A0MRZ7
    "uniprot": (
        r"^uniprot:[A-Z][A-Z0-9]{5}([A-Z0-9]{4})?$",
        "UniProt should be 'uniprot:' followed by 6 or 10 alphanumeric characters"
    ),
    # PDB: 4 alphanumeric characters (first is digit 1-9)
    # Valid: pdb:8A5S, pdb:1ABC
    "pdb": (
        r"^pdb:\d[A-Za-z0-9]{3}$",
        "PDB ID should be 'pdb:' followed by 4 alphanumeric characters (first is digit)"
    ),
    # TaxID: numeric only
    # Valid: taxid:469008
    "taxid": (
        r"^taxid:\d+$",
        "TaxID should be 'taxid:' followed by digits only"
    ),
    # CID (PubChem): numeric only
    # Valid: cid:78165
    "cid": (
        r"^cid:\d+$",
        "PubChem CID should be 'cid:' followed by digits only"
    ),
}


def _extract_external_ids(obj: Any, path: str = "") -> List[Dict]:
    """
    Extract all external identifier strings from the JSON.
    Looks for fields like 'identifiers', 'external_databases', 'additional_identifiers',
    and 'id' fields that contain known prefixes.
    """
    results = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k

            # Check specific fields that contain identifiers
            if k in ("identifiers", "external_databases", "additional_identifiers"):
                if isinstance(v, list):
                    for i, item in enumerate(v):
                        if isinstance(item, str):
                            results.append({
                                "path": f"{new_path}[{i}]",
                                "value": item
                            })
            # Check id fields with known prefixes
            elif k == "id" and isinstance(v, str):
                # Only check IDs that look like external identifiers (have a prefix:)
                if ":" in v and any(v.startswith(prefix + ":") for prefix in
                    ["orcid", "inchikey", "uniprot", "pdb", "taxid", "cid", "ror"]):
                    results.append({
                        "path": new_path,
                        "value": v
                    })
            else:
                results.extend(_extract_external_ids(v, new_path))

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            results.extend(_extract_external_ids(v, f"{path}[{i}]"))
    elif isinstance(obj, str):
        # Check if standalone string looks like an identifier
        if ":" in obj:
            for prefix in ["orcid", "inchikey", "uniprot", "pdb", "taxid", "cid"]:
                if obj.startswith(prefix + ":") or obj.startswith(prefix + ": "):
                    results.append({
                        "path": path,
                        "value": obj
                    })
                    break

    return results


def run_external_id_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Validate format of external identifiers (ORCID, UniProt, PDB, InChI, etc.)
    Deterministic - no LLM needed, zero false positives.
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    external_ids = _extract_external_ids(record_json)

    for ext_id in external_ids:
        value = ext_id["value"]
        path = ext_id["path"]

        # Determine which pattern to use based on prefix
        prefix = value.split(":")[0].lower() if ":" in value else ""

        if prefix in EXTERNAL_ID_PATTERNS:
            pattern, expected_format = EXTERNAL_ID_PATTERNS[prefix]

            # Normalize space after prefix (MBDB form inserts "prefix: value")
            normalized = re.sub(r"^(\w+):\s+", r"\1:", value)

            if not re.match(pattern, normalized):
                # Determine specific issue
                if prefix == "orcid" and "https://" in value:
                    message = "ORCID contains URL prefix - should be just the ID"
                    suggested_fix = re.sub(r"orcid:https://orcid\.org/", "orcid:", value)
                else:
                    message = f"Invalid {prefix.upper()} format"
                    suggested_fix = expected_format

                line = find_line_for_path_and_value(json_pretty, path, value)

                issues.append({
                    "path": path,
                    "severity": "warning",
                    "category": "format",
                    "message": message,
                    "validator": "external_ids",
                    "value": value,
                    "suggested_fix": suggested_fix,
                    "line": line
                })

    return issues


# ============== WHITESPACE VALIDATION (Deterministic) ==============

# Fields to check for whitespace issues
WHITESPACE_CHECK_FIELDS = {
    "name", "title", "grant_id", "pid", "journal", "publisher",
    "family_name", "given_name", "city", "country", "state"
}


def _extract_string_fields_for_whitespace(obj: Any, path: str = "") -> List[Dict]:
    """
    Extract string fields that should be checked for whitespace issues.
    Focuses on names, titles, IDs - not descriptions or free text.
    """
    results = []

    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k

            if isinstance(v, str):
                # Check if this is a field we should validate
                if k in WHITESPACE_CHECK_FIELDS or k.endswith("_id") or k.endswith("_name"):
                    results.append({
                        "path": new_path,
                        "value": v,
                        "field_name": k
                    })
            else:
                results.extend(_extract_string_fields_for_whitespace(v, new_path))

    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            results.extend(_extract_string_fields_for_whitespace(v, f"{path}[{i}]"))

    return results


def run_whitespace_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check for whitespace issues in names, titles, and identifiers.
    Deterministic - no LLM needed, zero false positives.

    Checks for:
    - Leading whitespace
    - Trailing whitespace
    - Multiple consecutive spaces
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    string_fields = _extract_string_fields_for_whitespace(record_json)

    # Deduplicate by value - report each unique problematic value only once
    # This avoids reporting the same issue multiple times when a value is
    # defined once but referenced in many places (e.g., chemical_environment.name)
    seen_values: Dict[str, Dict] = {}
    for field in string_fields:
        value = field["value"]
        if value and value not in seen_values:
            seen_values[value] = field

    unique_fields = list(seen_values.values())

    for field in unique_fields:
        value = field["value"]
        path = field["path"]
        field_name = field["field_name"]

        if not value:
            continue

        # Check for leading whitespace
        if value != value.lstrip():
            line = find_line_for_path_and_value(json_pretty, path, value)
            issues.append({
                "path": path,
                "severity": "warning",
                "category": "format",
                "message": f"'{field_name}' has leading whitespace",
                "validator": "whitespace",
                "value": value,
                "suggested_fix": value.strip(),
                "line": line
            })
        # Check for trailing whitespace
        elif value != value.rstrip():
            line = find_line_for_path_and_value(json_pretty, path, value)
            issues.append({
                "path": path,
                "severity": "warning",
                "category": "format",
                "message": f"'{field_name}' has trailing whitespace",
                "validator": "whitespace",
                "value": value,
                "suggested_fix": value.strip(),
                "line": line
            })
        # Check for multiple consecutive spaces (but not in descriptions)
        elif "  " in value and field_name not in ("description", "additional_specifications"):
            line = find_line_for_path_and_value(json_pretty, path, value)
            issues.append({
                "path": path,
                "severity": "warning",
                "category": "format",
                "message": f"'{field_name}' contains multiple consecutive spaces",
                "validator": "whitespace",
                "value": value,
                "suggested_fix": " ".join(value.split()),
                "line": line
            })

    return issues


# ============== PLACEHOLDER VALUE VALIDATION (Deterministic) ==============

# Contexts where -1 is likely a placeholder (not a valid value)
PLACEHOLDER_CONTEXTS = {"concentration", "reference_power", "volume", "cell_volume", "injection_volume"}


def run_placeholder_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Detect placeholder values (-1) and invalid negative values.
    Deterministic - no LLM needed, zero false positives.

    Catches:
    - Value of -1 in concentration, reference_power, volume fields (common placeholder)
    - Negative concentrations (always invalid)
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    for node in iter_numeric_nodes(record_json):
        value = node["value"]
        path = node["path"]
        context = node["context_key"]

        # Skip non-negative values
        if value >= 0:
            continue

        # Check for -1 placeholder pattern in specific contexts
        if value == -1 and context in PLACEHOLDER_CONTEXTS:
            line = find_line_for_path_and_value(json_pretty, path, str(value))
            issues.append({
                "path": path,
                "severity": "warning",
                "category": "placeholder",
                "message": f"Value of -1 appears to be a placeholder in '{context}'",
                "validator": "placeholder_values",
                "value": value,
                "suggested_fix": "Replace with actual measured value or remove field",
                "line": line
            })
        # Check for any negative concentration (always invalid)
        elif "concentration" in path.lower() and value < 0:
            line = find_line_for_path_and_value(json_pretty, path, str(value))
            issues.append({
                "path": path,
                "severity": "error",
                "category": "range",
                "message": f"Concentration cannot be negative: {value}",
                "validator": "placeholder_values",
                "value": value,
                "suggested_fix": "Use a positive concentration value",
                "line": line
            })

    return issues
