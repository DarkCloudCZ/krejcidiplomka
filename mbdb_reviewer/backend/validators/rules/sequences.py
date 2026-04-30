"""
Sequence validation rules.

This module contains the two rule-based sequence validators kept in the final
thesis scope:
- sequence length vs molecular weight
- sequence content
"""

import json
import re
from typing import Any, Dict, List, Optional

from utils.json_utils import find_line_for_path_and_value


# ============== SEQUENCE VS MOLECULAR WEIGHT VALIDATION (Deterministic) ==============

def _count_sequence_residues(sequence: str, polymer_type: str) -> Optional[int]:
    """
    Count residues in a sequence, handling various formats.
    Returns None if sequence format is unrecognized.
    """
    if not sequence:
        return None

    # Clean whitespace
    clean_seq = re.sub(r'\s+', '', sequence)

    # Handle DNA with "Forward:" and "Reverse:" labels
    if "polydeoxyribonucleotide" in polymer_type:
        # Try to extract just the forward strand
        # Format: "Forward: 5'- TTT... -3' Reverse: 5'- CAT... -3'"
        forward_match = re.search(r"Forward[:\s]*5['\-\s]*([ACGT\-\s]+)[3'\-\s]*", sequence, re.IGNORECASE)
        if forward_match:
            strand = re.sub(r'[\s\-\']', '', forward_match.group(1))
            return len(strand)

        # If no Forward/Reverse, just count nucleotides
        nucleotides = re.sub(r'[^ACGTU]', '', clean_seq.upper())
        return len(nucleotides) if nucleotides else None

    # For proteins, count amino acid letters
    elif "polypeptide" in polymer_type:
        # Remove common non-sequence characters
        aa_seq = re.sub(r'[^ACDEFGHIKLMNPQRSTVWY]', '', clean_seq.upper())
        return len(aa_seq) if aa_seq else None

    return None


def run_sequence_mw_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check if sequence length matches molecular weight.
    Deterministic - no LLM needed.

    Handles both top-level entities and nested components of Molecular
    assembly entities. Each component carries its own sequence, polymer_type,
    molecular_weight, and (optionally) modifications.

    Expected ratios:
    - Proteins: ~110 Da per amino acid
    - DNA: ~330 Da per nucleotide (single strand, ~660 for dsDNA)

    Uses 15% tolerance to account for modifications, tags, etc.
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    def _check(
        sequence: str,
        polymer_type: str,
        name: str,
        path: str,
        mw: Dict[str, Any],
        modifications: Any,
    ) -> None:
        """Run the length-vs-MW check on a single sequence."""
        if not sequence or not mw or not mw.get("value"):
            return

        # Count residues
        residue_count = _count_sequence_residues(sequence, polymer_type)
        if not residue_count or residue_count < 5:
            return  # Too short or unrecognized

        # Get MW in Daltons
        mw_value = mw["value"]
        mw_unit = mw.get("unit", "Da")
        if "kDa" in mw_unit:
            mw_value *= 1000
        # g/mol is approximately equal to Da

        # Calculate expected MW
        if "polypeptide" in polymer_type:
            da_per_residue = 110
            tolerance = 0.15  # 15% tolerance (Jan's 10-20% request)
            residue_type = "amino acids"
        elif "polydeoxyribonucleotide" in polymer_type:
            da_per_residue = 330
            tolerance = 0.15
            residue_type = "nucleotides"

            # Check if double-stranded DNA (dsDNA)
            is_double_stranded = (
                name.lower().startswith("ds") or
                "double" in name.lower() or
                ("forward" in sequence.lower() and "reverse" in sequence.lower())
            )
            if is_double_stranded:
                da_per_residue = 660  # 330 × 2 for double strand
                residue_type = "bp (double-stranded)"
        else:
            return  # Unknown polymer type

        expected_mw = residue_count * da_per_residue
        if expected_mw <= 0:
            return

        ratio = mw_value / expected_mw
        if (1 - tolerance) <= ratio <= (1 + tolerance):
            return

        # Land on the `molecular_weight` field of this specific entity/component.
        # Strategy: anchor on the unique `"name": "<name>"` line, then scan
        # outward (both directions) for the closest `"molecular_weight":` key.
        # Alphabetically sorted keys put MW before NAME; unsorted input can put
        # it after — so we pick whichever is nearer. Falls back to the name
        # line if no MW key is found within the window.
        name_line = find_line_for_path_and_value(json_pretty, path, name)
        line = name_line
        if name_line is not None:
            all_lines = json_pretty.split("\n")
            name_idx = name_line - 1  # 0-indexed
            closest = None
            closest_dist = None
            for j in range(max(0, name_idx - 60), min(len(all_lines), name_idx + 60)):
                if '"molecular_weight"' in all_lines[j]:
                    dist = abs(j - name_idx)
                    if closest_dist is None or dist < closest_dist:
                        closest = j
                        closest_dist = dist
            if closest is not None:
                line = closest + 1

        message = f"Sequence length may not match molecular weight for '{name}'"
        if not modifications:
            message += " (no post-translational modifications specified to explain difference)"
            severity = "warning"
        else:
            severity = "info"  # Less severe if modifications exist

        issues.append({
            "path": path,
            "severity": severity,
            "category": "cross_field",
            "message": message,
            "validator": "sequence_mw",
            "value": f"{residue_count} {residue_type} → expected ~{expected_mw:,.0f} Da, actual {mw_value:,.0f} Da",
            "suggested_fix": "Verify sequence and molecular weight are correct, or add modification details if applicable",
            "line": line
        })

    metadata = record_json.get("metadata", {})
    gp = metadata.get("general_parameters", {})
    entities = gp.get("entities_of_interest", [])

    for idx, entity in enumerate(entities):
        entity_name = entity.get("name", f"Entity {idx}")

        # Top-level entity (polymer_type is the real discriminator, not entity.type).
        _check(
            entity.get("sequence", ""),
            entity.get("polymer_type", ""),
            entity_name,
            f"metadata.general_parameters.entities_of_interest[{idx}]",
            entity.get("molecular_weight", {}) or {},
            entity.get("modifications"),
        )

        # Components — Molecular assembly / multi-chain entities.
        for cj, comp in enumerate(entity.get("components") or []):
            comp_name = comp.get("name", f"{entity_name} component {cj}")
            _check(
                comp.get("sequence", ""),
                comp.get("polymer_type", ""),
                comp_name,
                f"metadata.general_parameters.entities_of_interest[{idx}].components[{cj}]",
                comp.get("molecular_weight", {}) or {},
                comp.get("modifications"),
            )

    return issues


# ============== SEQUENCE CONTENT VALIDATION (Alphabet Check) ==============

def run_sequence_content_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check that sequence contains only valid letters for its polymer type.
    Deterministic alphabet validation - no LLM needed.

    Handles both top-level entities (type="Polymer") and nested components of
    Molecular assembly entities, where each component carries its own
    polymer_type and sequence.

    Jan's requirement: "Zkontrolovat, že ta sekvence proteinová jakože musí prostě ten protein existovat...
    není tam nějaký písmenko divný, nemá nějaký číslo."
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    # Valid alphabets per polymer type
    VALID_ALPHABETS = {
        "polypeptide": set("ACDEFGHIKLMNPQRSTVWY"),  # 20 amino acids
        "polydeoxyribonucleotide": set("ACGT"),       # DNA
        "polyribonucleotide": set("ACGU")             # RNA
    }

    def _check(sequence: str, polymer_type: str, name: str, path: str) -> None:
        """Run the alphabet check on a single sequence + polymer_type pair."""
        if not sequence or not polymer_type:
            return

        # Find matching alphabet
        valid_chars = None
        for type_key, alphabet in VALID_ALPHABETS.items():
            if type_key in polymer_type.lower():
                valid_chars = alphabet
                break
        if not valid_chars:
            return  # Unknown polymer type

        # Clean sequence: remove whitespace, convert to uppercase
        clean_seq = re.sub(r'\s+', '', sequence).upper()

        # Remove common formatting characters that are OK
        clean_seq = clean_seq.replace("-", "").replace("'", "").replace("3", "").replace("5", "")

        # For DNA with Forward/Reverse labels, extract just sequence letters
        if "forward" in clean_seq.lower() or "reverse" in clean_seq.lower():
            clean_seq = re.sub(r'\b(FORWARD|REVERSE|FWD|REV)\b', '', clean_seq, flags=re.IGNORECASE)
            clean_seq = re.sub(r'[:\-\s]+', '', clean_seq)

        # Find invalid characters
        invalid_chars = set(clean_seq) - valid_chars
        if not invalid_chars:
            return

        issues.append({
            "path": path,
            "severity": "error",
            "category": "sequence",
            "message": f"Sequence for '{name}' contains invalid characters: {', '.join(sorted(invalid_chars))}",
            "validator": "sequence_content",
            "value": f"Found: {', '.join(sorted(invalid_chars))}",
            "suggested_fix": f"Valid characters for {polymer_type}: {', '.join(sorted(valid_chars))}",
            "line": find_line_for_path_and_value(json_pretty, "sequence", sequence[:50])
        })

    entities = record_json.get("metadata", {}).get("general_parameters", {}).get("entities_of_interest", [])

    for idx, entity in enumerate(entities):
        entity_name = entity.get("name", f"Entity {idx}")

        # Top-level entity: check only if it has its own sequence + polymer_type.
        # The real discriminator is polymer_type (not entity.type), so we don't
        # gate on type == "Polymer" anymore — that gate would skip Molecular
        # assembly entities whose components carry the actual sequences.
        _check(
            entity.get("sequence", ""),
            entity.get("polymer_type", ""),
            entity_name,
            f"metadata.general_parameters.entities_of_interest[{idx}].sequence",
        )

        # Components — for Molecular assembly / multi-chain entities.
        for cj, comp in enumerate(entity.get("components") or []):
            comp_name = comp.get("name", f"{entity_name} component {cj}")
            _check(
                comp.get("sequence", ""),
                comp.get("polymer_type", ""),
                comp_name,
                f"metadata.general_parameters.entities_of_interest[{idx}].components[{cj}].sequence",
            )

    return issues


