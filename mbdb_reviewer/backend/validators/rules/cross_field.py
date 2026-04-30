"""
Cross-field validation rules.

This module contains the rule-based validators that compare multiple fields
within an MBDB record:
- date consistency
- data analysis references
- entity usage
- unit consistency
- result plausibility
"""

import json
from typing import Any, Dict, List
from utils.json_utils import find_line_for_path_and_value


# ============== DATE CONSISTENCY VALIDATION ==============

def run_date_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check date consistency across the record.
    Deterministic - no LLM needed.
    """
    from datetime import datetime, timedelta

    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)
    gp = record_json.get("metadata", {}).get("general_parameters", {})
    ri = gp.get("record_information", {})

    deposition = ri.get("deposition_date")
    available = ri.get("date_available")

    # Check deposition vs availability date
    if deposition and available:
        try:
            dep_date = datetime.strptime(deposition, "%Y-%m-%d")
            avail_date = datetime.strptime(available, "%Y-%m-%d")

            if dep_date > avail_date:
                issues.append({
                    "path": "metadata.general_parameters.record_information",
                    "severity": "error",
                    "category": "cross_field",
                    "message": "Deposition date is after availability date",
                    "validator": "date_consistency",
                    "value": f"deposition: {deposition}, available: {available}",
                    "line": find_line_for_path_and_value(json_pretty, "deposition_date", deposition)
                })
        except ValueError:
            issues.append({
                "path": "metadata.general_parameters.record_information",
                "severity": "error",
                "category": "format",
                "message": "Date format invalid (expected YYYY-MM-DD)",
                "validator": "date_consistency",
                "value": f"deposition: {deposition}, available: {available}"
            })

    # Check for dates too far in future
    if available:
        try:
            avail_date = datetime.strptime(available, "%Y-%m-%d")
            one_year_future = datetime.now() + timedelta(days=365)
            if avail_date > one_year_future:
                issues.append({
                    "path": "metadata.general_parameters.record_information.date_available",
                    "severity": "warning",
                    "category": "cross_field",
                    "message": "Availability date is more than 1 year in future",
                    "validator": "date_consistency",
                    "value": available,
                    "line": find_line_for_path_and_value(json_pretty, "date_available", available)
                })
        except ValueError:
            pass

    return issues


# ============== DATA ANALYSIS REFERENCES VALIDATION ==============

def run_data_analysis_refs_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check that data_analysis references valid measurement and result IDs.
    Deterministic - no LLM needed.
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)
    metadata = record_json.get("metadata", {})
    msp = metadata.get("method_specific_parameters", {})
    gp = metadata.get("general_parameters", {})

    # Collect all measurement IDs
    measurements = msp.get("measurements", [])
    measurement_ids = {m.get("id") for m in measurements if m.get("id")}

    # Collect all result IDs
    results = gp.get("results", [])
    result_ids = {r.get("id") for r in results if r.get("id")}

    # Check data_analysis references
    data_analyses = msp.get("data_analysis", [])
    referenced_measurement_ids = set()

    for idx, da in enumerate(data_analyses):
        # Check measurement references
        da_measurements = da.get("measurements", [])
        for m_ref in da_measurements:
            m_id = m_ref.get("id")
            if m_id:
                referenced_measurement_ids.add(m_id)
                if m_id not in measurement_ids:
                    issues.append({
                        "path": f"metadata.method_specific_parameters.data_analysis[{idx}].measurements",
                        "severity": "error",
                        "category": "cross_field",
                        "message": f"Data analysis references non-existent measurement ID",
                        "validator": "data_analysis_refs",
                        "value": m_id,
                        "line": find_line_for_path_and_value(json_pretty, "measurements", m_id)
                    })

        # Check result references
        da_results = da.get("results", [])
        for r_ref in da_results:
            r_id = r_ref.get("id")
            if r_id and r_id not in result_ids:
                issues.append({
                    "path": f"metadata.method_specific_parameters.data_analysis[{idx}].results",
                    "severity": "error",
                    "category": "cross_field",
                    "message": f"Data analysis references non-existent result ID",
                    "validator": "data_analysis_refs",
                    "value": r_id,
                    "line": find_line_for_path_and_value(json_pretty, "results", r_id)
                })

    # Note: We don't check for "unanalyzed measurements" because:
    # - data_analysis typically references only representative measurements
    # - It's normal for most measurements in a titration series to not be explicitly listed

    return issues


# ============== ENTITY USAGE VALIDATION ==============

def run_entity_usage_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check entity usage consistency - unused entities, orphan references.
    Deterministic - no LLM needed.
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)
    metadata = record_json.get("metadata", {})
    gp = metadata.get("general_parameters", {})
    msp = metadata.get("method_specific_parameters", {})

    # Collect defined entity IDs
    entities = gp.get("entities_of_interest", [])
    entity_ids = {e.get("id") for e in entities if e.get("id")}
    entity_names = {e.get("id"): e.get("name", "") for e in entities}

    # Collect chemical environment IDs
    chem_envs = gp.get("chemical_environments", [])
    chem_env_ids = {ce.get("id") for ce in chem_envs if ce.get("id")}

    # Track used entity IDs and chem env IDs
    used_entity_ids = set()
    used_chem_env_ids = set()

    # Scan measurements for entity and chem env usage
    measurements = msp.get("measurements", [])
    for m_idx, measurement in enumerate(measurements):
        sample = measurement.get("sample", {})

        # Check chemical environment reference (MST/BLI: sample, ITC: sample_in_cell/syringe)
        chem_env_paths = [("sample.chemical_environment", sample.get("chemical_environment", {}))]
        for sample_key in ("sample_in_cell", "sample_in_syringe"):
            itc_sample = measurement.get(sample_key, {})
            if itc_sample.get("chemical_environment"):
                chem_env_paths.append((f"{sample_key}.chemical_environment", itc_sample["chemical_environment"]))

        for ce_path, chem_env_ref in chem_env_paths:
            ce_id = chem_env_ref.get("id")
            if ce_id:
                used_chem_env_ids.add(ce_id)
                if ce_id not in chem_env_ids:
                    issues.append({
                        "path": f"metadata.method_specific_parameters.measurements[{m_idx}].{ce_path}",
                        "severity": "error",
                        "category": "cross_field",
                        "message": "Sample references undefined chemical environment",
                        "validator": "entity_usage",
                        "value": ce_id
                    })

        # Check ligand entity references
        for lig_idx, ligand in enumerate(sample.get("ligands", [])):
            ent = ligand.get("entity", {})
            ent_id = ent.get("id")
            ent_ref_name = ent.get("name", "")
            if ent_id:
                used_entity_ids.add(ent_id)
                if ent_id not in entity_ids:
                    issues.append({
                        "path": f"metadata.method_specific_parameters.measurements[{m_idx}].sample.ligands[{lig_idx}]",
                        "severity": "error",
                        "category": "cross_field",
                        "message": "Ligand references entity not in entities_of_interest",
                        "validator": "entity_usage",
                        "value": ent_id
                    })
                elif ent_ref_name:
                    # Check name consistency
                    defined_name = entity_names.get(ent_id, "")
                    if defined_name and ent_ref_name != defined_name:
                        issues.append({
                            "path": f"metadata.method_specific_parameters.measurements[{m_idx}].sample.ligands[{lig_idx}].entity.name",
                            "severity": "warning",
                            "category": "cross_field",
                            "message": f"Entity name mismatch: reference says '{ent_ref_name}' but definition says '{defined_name}'",
                            "validator": "entity_usage",
                            "value": ent_ref_name,
                            "suggested_fix": f"Change name to '{defined_name}' to match entity definition"
                        })

        # Check target entity references
        for tgt_idx, target in enumerate(sample.get("targets", [])):
            ent = target.get("entity", {})
            ent_id = ent.get("id")
            ent_ref_name = ent.get("name", "")
            if ent_id:
                used_entity_ids.add(ent_id)
                if ent_id not in entity_ids:
                    issues.append({
                        "path": f"metadata.method_specific_parameters.measurements[{m_idx}].sample.targets[{tgt_idx}]",
                        "severity": "error",
                        "category": "cross_field",
                        "message": "Target references entity not in entities_of_interest",
                        "validator": "entity_usage",
                        "value": ent_id
                    })
                elif ent_ref_name:
                    # Check name consistency
                    defined_name = entity_names.get(ent_id, "")
                    if defined_name and ent_ref_name != defined_name:
                        issues.append({
                            "path": f"metadata.method_specific_parameters.measurements[{m_idx}].sample.targets[{tgt_idx}].entity.name",
                            "severity": "warning",
                            "category": "cross_field",
                            "message": f"Entity name mismatch: reference says '{ent_ref_name}' but definition says '{defined_name}'",
                            "validator": "entity_usage",
                            "value": ent_ref_name,
                            "suggested_fix": f"Change name to '{defined_name}' to match entity definition"
                        })

        # Check analyte entity references (BLI and other techniques)
        for ana_idx, analyte in enumerate(sample.get("analytes", [])):
            ent = analyte.get("entity", {})
            ent_id = ent.get("id")
            ent_ref_name = ent.get("name", "")
            if ent_id:
                used_entity_ids.add(ent_id)
                if ent_id not in entity_ids:
                    issues.append({
                        "path": f"metadata.method_specific_parameters.measurements[{m_idx}].sample.analytes[{ana_idx}]",
                        "severity": "error",
                        "category": "cross_field",
                        "message": "Analyte references entity not in entities_of_interest",
                        "validator": "entity_usage",
                        "value": ent_id
                    })
                elif ent_ref_name:
                    defined_name = entity_names.get(ent_id, "")
                    if defined_name and ent_ref_name != defined_name:
                        issues.append({
                            "path": f"metadata.method_specific_parameters.measurements[{m_idx}].sample.analytes[{ana_idx}].entity.name",
                            "severity": "warning",
                            "category": "cross_field",
                            "message": f"Entity name mismatch: reference says '{ent_ref_name}' but definition says '{defined_name}'",
                            "validator": "entity_usage",
                            "value": ent_ref_name,
                            "suggested_fix": f"Change name to '{defined_name}' to match entity definition"
                        })

        # Check ITC-specific entity references (sample_in_cell / sample_in_syringe)
        for sample_key in ("sample_in_cell", "sample_in_syringe"):
            itc_sample = measurement.get(sample_key, {})
            for container_key in ("targets", "ligands"):
                for itc_idx, ent_container in enumerate(itc_sample.get(container_key, [])):
                    ent = ent_container.get("entity", {})
                    ent_id = ent.get("id")
                    ent_ref_name = ent.get("name", "")
                    if ent_id:
                        used_entity_ids.add(ent_id)
                        if ent_id not in entity_ids:
                            issues.append({
                                "path": f"metadata.method_specific_parameters.measurements[{m_idx}].{sample_key}.{container_key}[{itc_idx}]",
                                "severity": "error",
                                "category": "cross_field",
                                "message": f"ITC {container_key[:-1]} references entity not in entities_of_interest",
                                "validator": "entity_usage",
                                "value": ent_id
                            })
                        elif ent_ref_name:
                            defined_name = entity_names.get(ent_id, "")
                            if defined_name and ent_ref_name != defined_name:
                                issues.append({
                                    "path": f"metadata.method_specific_parameters.measurements[{m_idx}].{sample_key}.{container_key}[{itc_idx}].entity.name",
                                    "severity": "warning",
                                    "category": "cross_field",
                                    "message": f"Entity name mismatch: reference says '{ent_ref_name}' but definition says '{defined_name}'",
                                    "validator": "entity_usage",
                                    "value": ent_ref_name,
                                    "suggested_fix": f"Change name to '{defined_name}' to match entity definition"
                                })

    # Check results.entities_involved for entity usage
    results = gp.get("results", [])
    for result in results:
        for ent_inv in result.get("entities_involved", []):
            ent_id = ent_inv.get("entity", {}).get("id")
            if ent_id:
                used_entity_ids.add(ent_id)

    # Check for unused entities
    unused_entities = entity_ids - used_entity_ids
    for ent_id in unused_entities:
        name = entity_names.get(ent_id, "")
        issues.append({
            "path": "metadata.general_parameters.entities_of_interest",
            "severity": "warning",
            "category": "cross_field",
            "message": f"Entity defined but never used in measurements: {name}",
            "validator": "entity_usage",
            "value": ent_id
        })

    # Check for unused chemical environments
    unused_chem_envs = chem_env_ids - used_chem_env_ids
    for ce_id in unused_chem_envs:
        issues.append({
            "path": "metadata.general_parameters.chemical_environments",
            "severity": "warning",
            "category": "cross_field",
            "message": "Chemical environment defined but never used",
            "validator": "entity_usage",
            "value": ce_id
        })

    return issues


# ============== UNIT CONSISTENCY VALIDATION ==============

def run_unit_consistency_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check unit consistency across the record.
    Deterministic - no LLM needed.

    Checks:
    1. Same entity uses consistent units across measurements
    2. Concentration units are valid (not volume units like mL)
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    # Valid concentration units
    VALID_CONCENTRATION_UNITS = {
        "nM", "µM", "uM", "mM", "M",  # Molar units
        "pM", "fM",  # Low concentration molar
        "mg/mL", "µg/mL", "ug/mL", "ng/mL", "pg/mL",  # Mass/volume
        "g/L", "mg/L", "µg/L", "ug/L",  # g/L variants
        "% (w/v)", "% (v/v)", "%",  # Percentage
        "mol/L", "mmol/L", "µmol/L", "umol/L",  # mol/L variants
    }

    # Collect all concentration units by entity
    entity_concentration_units: Dict[str, List[tuple]] = {}  # entity_id -> [(unit, path), ...]

    metadata = record_json.get("metadata", {})
    msp = metadata.get("method_specific_parameters", {})

    measurements = msp.get("measurements", [])
    for m_idx, measurement in enumerate(measurements):
        sample = measurement.get("sample", {})

        # Check ligand concentrations
        for lig_idx, ligand in enumerate(sample.get("ligands", [])):
            ent = ligand.get("entity", {})
            ent_id = ent.get("id")
            conc = ligand.get("concentration", {})
            unit = conc.get("unit")
            if unit:
                path = f"metadata.method_specific_parameters.measurements[{m_idx}].sample.ligands[{lig_idx}].concentration.unit"
                # Check for invalid unit
                if unit not in VALID_CONCENTRATION_UNITS:
                    issues.append({
                        "path": path,
                        "severity": "error",
                        "category": "cross_field",
                        "message": f"Invalid concentration unit: '{unit}'. Expected molarity (nM, µM, mM) or mass/volume (mg/mL, etc.)",
                        "validator": "unit_consistency",
                        "value": unit,
                        "suggested_fix": "Use a valid concentration unit like nM, µM, mM, M, mg/mL"
                    })
                # Track for consistency check
                if ent_id:
                    if ent_id not in entity_concentration_units:
                        entity_concentration_units[ent_id] = []
                    entity_concentration_units[ent_id].append((unit, path))

        # Check target concentrations
        for tgt_idx, target in enumerate(sample.get("targets", [])):
            ent = target.get("entity", {})
            ent_id = ent.get("id")
            conc = target.get("concentration", {})
            unit = conc.get("unit")
            if unit:
                path = f"metadata.method_specific_parameters.measurements[{m_idx}].sample.targets[{tgt_idx}].concentration.unit"
                # Check for invalid unit
                if unit not in VALID_CONCENTRATION_UNITS:
                    issues.append({
                        "path": path,
                        "severity": "error",
                        "category": "cross_field",
                        "message": f"Invalid concentration unit: '{unit}'. Expected molarity (nM, µM, mM) or mass/volume (mg/mL, etc.)",
                        "validator": "unit_consistency",
                        "value": unit,
                        "suggested_fix": "Use a valid concentration unit like nM, µM, mM, M, mg/mL"
                    })
                # Track for consistency check
                if ent_id:
                    if ent_id not in entity_concentration_units:
                        entity_concentration_units[ent_id] = []
                    entity_concentration_units[ent_id].append((unit, path))

    # Check for mixed units per entity
    for ent_id, unit_list in entity_concentration_units.items():
        units = set(u for u, p in unit_list)
        if len(units) > 1:
            issues.append({
                "path": "metadata.method_specific_parameters.measurements",
                "severity": "warning",
                "category": "cross_field",
                "message": f"Same entity uses different concentration units: {', '.join(sorted(units))}",
                "validator": "unit_consistency",
                "value": ent_id,
                "suggested_fix": "Use consistent units for the same entity across all measurements"
            })

    return issues


# ============== RESULT PLAUSIBILITY VALIDATION ==============

def run_result_plausibility_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check result plausibility - error ranges, KD units, etc.
    Deterministic - no LLM needed.
    """
    issues = []
    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)
    gp = record_json.get("metadata", {}).get("general_parameters", {})

    results = gp.get("results", [])
    valid_kd_units = {"nM", "µM", "uM", "mM", "M", "pM", "fM"}
    valid_rate_units = {"s^-1", "1/s", "min^-1", "s⁻¹"}
    valid_kon_units = {"M^-1 s^-1", "M^-1s^-1", "1/(M·s)", "M⁻¹s⁻¹", "1/(Ms)"}

    for idx, result in enumerate(results):
        result_type = result.get("type", "")
        result_type_lower = result_type.lower()
        value = result.get("value")
        unit = result.get("unit")
        value_error = result.get("value_error", {})

        # Classify result type: kOff (rate) vs kon (association rate) vs KD (constant)
        is_koff = ("koff" in result_type_lower or "k_off" in result_type_lower
                   or ("dissociation" in result_type_lower and "rate" in result_type_lower))
        is_kon = ("kon" in result_type_lower or "k_on" in result_type_lower
                  or ("association" in result_type_lower and "rate" in result_type_lower))
        is_kd = (not is_koff and not is_kon
                 and ("KD" in result_type or "dissociation" in result_type_lower))

        # Check unit plausibility for each result type
        if is_kd:
            if unit and unit not in valid_kd_units:
                issues.append({
                    "path": f"metadata.general_parameters.results[{idx}]",
                    "severity": "warning",
                    "category": "cross_field",
                    "message": f"KD result has unusual unit: {unit}",
                    "validator": "result_plausibility",
                    "value": unit,
                    "suggested_fix": f"Expected one of: {', '.join(sorted(valid_kd_units))}"
                })
        elif is_koff:
            if unit and unit not in valid_rate_units:
                issues.append({
                    "path": f"metadata.general_parameters.results[{idx}]",
                    "severity": "warning",
                    "category": "cross_field",
                    "message": f"kOff result has unusual unit: {unit}",
                    "validator": "result_plausibility",
                    "value": unit,
                    "suggested_fix": f"Expected one of: {', '.join(sorted(valid_rate_units))}"
                })
        elif is_kon:
            if unit and unit not in valid_kon_units:
                issues.append({
                    "path": f"metadata.general_parameters.results[{idx}]",
                    "severity": "warning",
                    "category": "cross_field",
                    "message": f"kon result has unusual unit: {unit}",
                    "validator": "result_plausibility",
                    "value": unit,
                    "suggested_fix": f"Expected one of: {', '.join(sorted(valid_kon_units))}"
                })

        # Check error range plausibility
        if value and value_error:
            upper = value_error.get("upper")
            lower = value_error.get("lower")

            if upper is not None and value > 0 and upper > value:
                issues.append({
                    "path": f"metadata.general_parameters.results[{idx}].value_error",
                    "severity": "warning",
                    "category": "cross_field",
                    "message": "Error range is larger than the measured value",
                    "validator": "result_plausibility",
                    "value": f"value: {value}, error: ±{upper}",
                    "suggested_fix": "Verify the error calculation or report relative error"
                })

        # Check entities in result are defined
        entities_involved = result.get("entities_involved", [])
        entity_ids = {e.get("id") for e in gp.get("entities_of_interest", []) if e.get("id")}
        for ent_inv in entities_involved:
            ent_ref = ent_inv.get("entity", {})
            ent_id = ent_ref.get("id")
            if ent_id and ent_id not in entity_ids:
                issues.append({
                    "path": f"metadata.general_parameters.results[{idx}].entities_involved",
                    "severity": "error",
                    "category": "cross_field",
                    "message": "Result references undefined entity",
                    "validator": "result_plausibility",
                    "value": ent_id
                })

    return issues
