"""
Semantic Coherence Validator (AI-based)

AI-based semantic coherence check using comprehensive extracted summary.
Acts as the "big brain" that sees all important fields, texts, and protocols
to find correlations and contradictions across the entire record.

Checks for contradictions between different parts of the experiment record:
- Technique vs protocol descriptions
- Temperature consistency
- Measurement counts
- Instrument appropriateness
- Results plausibility
- Entity name consistency
- Sequence vs molecular weight vs modifications
- Buffer appropriateness
- Publication match
- Modifications vs entity claims
- Data analysis vs technique
"""

import json
import re
from typing import Dict, Any, List

from utils.llm_utils import create_chat_completion, get_chat_ai_client
from config import CHAT_AI_MODEL


def extract_semantic_summary(record_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract a comprehensive semantic summary from record for coherence checking.
    Includes all fields relevant for cross-record coherence: entities with modifications
    and quality controls, data analysis with fitting models and processing steps,
    all measurement names and protocol texts, chemical environments, and results.
    Returns ~2000-4000 tokens instead of full JSON (~10000+ tokens).
    """
    metadata = record_json.get("metadata", {})
    gp = metadata.get("general_parameters", {})
    msp = metadata.get("method_specific_parameters", {})

    # Basic experiment identity
    record_info = gp.get("record_information", {})
    publication = gp.get("associated_publication", {})
    instrument = gp.get("instrument", {})

    # Chemical environment - expanded with ionic strength and buffer detection
    chem_envs = gp.get("chemical_environments", [])
    chem_env_summary = []
    for ce in chem_envs:
        constituents = ce.get("constituents", [])
        # Detect buffer type from constituents
        buffer_type = next(
            (c.get("name", "") for c in constituents
             if any(buf in c.get("name", "").lower() for buf in ["buffer", "tris", "hepes", "phosphate", "mops"])),
            None
        )
        ce_entry = {
            "name": ce.get("name", ""),
            "ph": ce.get("ph"),
            "ionic_strength": ce.get("ionic_strength"),
            "buffer_type": buffer_type,
            "constituents": [c.get("name", "") for c in constituents],
        }
        if ce.get("additional_specifications"):
            ce_entry["additional_specifications"] = ce["additional_specifications"]
        chem_env_summary.append(ce_entry)

    # Entities - expanded with IDs, sequence snippets, and variant info
    entities = gp.get("entities_of_interest", [])
    entity_summary = []
    entity_ids = []
    for e in entities:
        ent = {
            "id": e.get("id", ""),
            "name": e.get("name", ""),
            "type": e.get("type", ""),
            "polymer_type": e.get("polymer_type", ""),
        }
        entity_ids.append(e.get("id", ""))
        if e.get("molecular_weight"):
            mw = e.get("molecular_weight", {})
            ent["molecular_weight"] = f"{mw.get('value')} {mw.get('unit', '')}"
        if e.get("sequence"):
            seq = e.get("sequence", "")
            ent["sequence_length"] = len(seq.replace(" ", ""))
            # Add sequence snippet for validation (first 30 chars)
            ent["sequence_snippet"] = seq[:30] + "..." if len(seq) > 30 else seq
        if e.get("variant"):
            ent["variant"] = e.get("variant", "")
        if e.get("expression_organism"):
            ent["expression_organism"] = e.get("expression_organism", {}).get("title", {}).get("en", "")
        if e.get("source_organism"):
            ent["source_organism"] = e.get("source_organism", {}).get("title", {}).get("en", "")
        # Modifications - critical for variant-sequence cross-checks
        mods = e.get("modifications")
        if mods and isinstance(mods, dict):
            mod_summary = {}
            for mod_category in ("biological_postprocessing", "chemical", "biological"):
                mod_list = mods.get(mod_category, [])
                if mod_list:
                    mod_summary[mod_category] = [
                        {k: v for k, v in mod.items() if k in ("type", "position", "description")}
                        for mod in mod_list
                    ]
            if mod_summary:
                ent["modifications"] = mod_summary
        # Quality controls
        qc = e.get("quality_controls")
        if qc and isinstance(qc, dict):
            qc_summary = {}
            for qc_type, qc_data in qc.items():
                if isinstance(qc_data, dict) and qc_data.get("assessed") == "Yes":
                    qc_entry = {"assessed": "Yes"}
                    if qc_data.get("method"):
                        qc_entry["method"] = qc_data["method"]
                    if qc_data.get("purity_percentage"):
                        qc_entry["purity_percentage"] = qc_data["purity_percentage"]
                    qc_summary[qc_type] = qc_entry
            if qc_summary:
                ent["quality_controls"] = qc_summary
        # Additional specifications (free-text researcher notes)
        if e.get("additional_specifications"):
            ent["additional_specifications"] = e["additional_specifications"]
        # Components (for Molecular assembly / multi-chain entities)
        comps = e.get("components") or []
        if comps:
            comp_summary = []
            for c in comps:
                c_entry = {
                    "name": c.get("name", ""),
                    "type": c.get("type", ""),
                }
                if c.get("source_organism"):
                    c_entry["source_organism"] = (
                        c.get("source_organism", {}).get("title", {}).get("en", "")
                    )
                if c.get("expression_organism"):
                    c_entry["expression_organism"] = (
                        c.get("expression_organism", {}).get("title", {}).get("en", "")
                    )
                if c.get("molecular_weight"):
                    cmw = c["molecular_weight"]
                    c_entry["molecular_weight"] = f"{cmw.get('value')} {cmw.get('unit', '')}"
                cseq = c.get("sequence", "")
                if cseq:
                    c_entry["sequence_length"] = len(cseq.replace(" ", "").replace("\n", ""))
                    c_entry["sequence_snippet"] = cseq[:30] + "..." if len(cseq) > 30 else cseq
                comp_summary.append(c_entry)
            ent["components"] = comp_summary
        entity_summary.append(ent)

    # Measurements summary - expanded with names
    measurements = msp.get("measurements", [])
    concentrations = []
    protocol_texts = []
    measurement_names = []

    for m in measurements:
        measurement_names.append(m.get("name", ""))

        # MST/BLI style: sample.ligands
        sample = m.get("sample", {})
        for ligand in sample.get("ligands", []):
            conc = ligand.get("concentration", {})
            if conc.get("value") is not None:
                concentrations.append(conc.get("value"))
        # ITC style: sample_in_cell / sample_in_syringe
        for sample_key in ("sample_in_cell", "sample_in_syringe"):
            itc_sample = m.get(sample_key, {})
            for target in itc_sample.get("targets", []):
                conc = target.get("concentration", {})
                if conc.get("value") is not None:
                    concentrations.append(conc.get("value"))
        # Collect protocol texts from all sources
        for prep in sample.get("preparation_protocol", []):
            desc = prep.get("description", "")
            if desc and desc not in protocol_texts:
                protocol_texts.append(desc)

    # Data analysis - fitting models, software, processing descriptions
    data_analysis_list = msp.get("data_analysis", [])
    data_analysis_summary = []
    for da in data_analysis_list:
        da_entry = {}
        fitting = da.get("data_fitting")
        if fitting:
            da_entry["fitting_model"] = fitting.get("model", "")
            if fitting.get("software_name"):
                da_entry["fitting_software"] = fitting["software_name"]
        processing = da.get("data_processing", [])
        if processing:
            da_entry["processing_steps"] = [
                {"name": step.get("name", ""), "description": step.get("description", "")}
                for step in processing
            ]
        if da.get("measurements"):
            da_entry["measurement_refs"] = [m.get("name", "") for m in da["measurements"] if m.get("name")]
        if da.get("results"):
            da_entry["result_refs"] = [r.get("name", "") for r in da["results"] if r.get("name")]
        if da_entry:
            data_analysis_summary.append(da_entry)

    # Measurement protocol steps (BLI/SPR)
    meas_protocol = msp.get("measurement_protocol", [])
    measurement_protocol_summary = [
        {"name": step.get("name", ""), "type": step.get("type", "")}
        for step in meas_protocol
    ] if meas_protocol else []

    # Results
    results = gp.get("results", [])
    result_summary = []
    for r in results:
        result_summary.append({
            "name": r.get("name", ""),
            "type": r.get("type", ""),
            "value": r.get("value"),
            "unit": r.get("unit", ""),
        })

    # Temperature
    temperature = msp.get("temperature", {})

    summary = {
        "technique": gp.get("technique", ""),
        "title": record_info.get("title", ""),
        "instrument": instrument.get("title", {}).get("en", ""),
        "instrument_name": instrument.get("name", ""),

        "publication": {
            "title": publication.get("title", ""),
            "journal": publication.get("journal", ""),
        } if publication else None,

        "protocol_texts": protocol_texts,

        "temperature": f"{temperature.get('value')} {temperature.get('unit', '')}" if temperature.get("value") else None,
        "chemical_environments": chem_env_summary,

        "entities": entity_summary,
        "entity_ids": entity_ids,

        "measurement_count": len(measurements),
        "measurement_names": measurement_names,
        "concentration_range": {
            "min": min(concentrations) if concentrations else None,
            "max": max(concentrations) if concentrations else None,
            "count": len(set(concentrations))
        } if concentrations else None,

        "results": result_summary,

        "external_databases": [
            db for e in entities
            for db in e.get("external_databases", [])
        ],
    }

    # Add optional sections only if present
    if data_analysis_summary:
        summary["data_analysis"] = data_analysis_summary
    if measurement_protocol_summary:
        summary["measurement_protocol_steps"] = measurement_protocol_summary

    return summary


def run_semantic_coherence_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    AI-based semantic coherence check using extracted summary.
    More efficient than sending whole JSON - ~90% token reduction.
    """
    client = get_chat_ai_client()

    # Extract focused summary
    summary = extract_semantic_summary(record_json)

    prompt = f"""You are validating an MBDB biophysics experiment record for SEMANTIC COHERENCE.

You are the "big brain" reviewer — you have a comprehensive summary of the entire record including
all entity details with modifications and quality controls, all measurement names and protocol texts,
data analysis fitting models and processing steps, and chemical environment details.
Use ALL of this information for cross-checking.

Check if all parts of this experiment tell a CONSISTENT story. Look for CONTRADICTIONS between:

1. TECHNIQUE vs PROTOCOL: Does the technique match what's described in protocol texts?
   - Example issue: Protocol mentions "SPR" but technique is "MST"

2. TEMPERATURE CONSISTENCY: Do temperature mentions agree?
   - Example issue: Protocol says "incubated at 4°C" but temperature field shows "25°C"

3. MEASUREMENT COUNT: Does described count match actual?
   - Example issue: Protocol says "20 titration points" but only 5 measurements

4. INSTRUMENT MATCH: Is instrument appropriate for technique?
   - Example issue: Instrument is "Biacore" (SPR) but technique is "MST"

5. RESULTS PLAUSIBILITY: Are results within tested concentration range?
   - Example issue: EC50 of 10 µM but concentrations only go from 1-100 nM
   - NOTE: For ITC, a low concentration_range count (2-3) is NORMAL — ITC uses injections
     within a single measurement, not separate measurements at different concentrations.
     Do NOT flag low concentration counts for ITC records.

6. ENTITY CONSISTENCY: Are entity names/types consistent throughout?
   - Example issue: Entity called "Lysozyme" in one place, "LYZ" elsewhere
   - Apply this ALSO at the component level: each component's `source_organism`
     and `expression_organism` must be biologically consistent with the
     component's name. A "Hemoglobin subunit alpha" with source_organism
     "Lactococcus phage" is impossible — hemoglobin is a vertebrate protein.
     Check every component of multi-chain entities (components[]), not just
     the top-level entity.

7. SEQUENCE vs MOLECULAR WEIGHT: Does sequence length match molecular weight?
   - For proteins: ~110 Da per amino acid (e.g., 200 residues ≈ 22 kDa)
   - Example issue: MW says 25 kDa but sequence has 50 residues (~5.5 kDa)
   - Apply this check PER COMPONENT for multi-chain entities. Example issue:
     a component named "Hemoglobin subunit alpha" with MW 16 kDa but
     sequence_length 121 (expected ~145 residues for 16 kDa) — this indicates
     a truncated sequence.

8. VARIANT vs SEQUENCE vs MODIFICATIONS: Do these three agree?
   - Example issue: Variant says "extra alanine (210 aa)" but sequence has 209 residues
   - Example issue: Modification says "fMet cleaved" but sequence still starts with M
   - Example issue: Entity has His-tag modification but MW doesn't account for it

9. MEASUREMENT NAMES: Do measurement names match the entities/conditions?
   - Example issue: Name says "BSA 100 µM" but sample contains EL222

10. BUFFER APPROPRIATENESS: Is buffer suitable for the sample type?
    - Example issue: High ionic strength (>500 mM) with membrane proteins
    - Example issue: Extreme pH (<5 or >9) with typical proteins

11. PUBLICATION MATCH: Is the publication completely unrelated to the experiment?
    - A publication mentioning a different technique is NOT a contradiction — papers routinely
      cover multiple methods, and this record may represent only one part of the study.
    - Only flag if the publication seems entirely unrelated in topic or biology.
    - Example issue: Publication is about in vivo mouse imaging but experiment is an ITC binding assay
    - NOT an issue: Publication title mentions SPR but experiment is MST — both are binding assays

12. MODIFICATIONS vs ENTITY CLAIMS: Do modifications match entity descriptions?
    - Example issue: Variant says "C-term His-tag" but no His-tag in modifications list
    - Example issue: Chemical modification (fluorescent label) not reflected in molecular weight

13. DATA ANALYSIS vs TECHNIQUE: Does fitting model / processing match the technique?
    - Example issue: ITC experiment using SPR-specific fitting terminology
    - Example issue: Processing step description mentions different technique than declared

ONLY report actual CONTRADICTIONS or clear IMPLAUSIBILITIES.
Do NOT flag missing information - only flag when something contradicts something else.

SEVERITY GUIDE:
- Use "error" only for scientifically impossible contradictions (e.g., EC50 outside the tested concentration range, instrument physically incompatible with the technique).
- Use "warning" for metadata inconsistencies that are likely mistakes but not impossible (e.g., data_analysis references fewer measurements than expected for the stated fit, publication title suggests a different method, name mismatches).
- When in doubt, use "warning".

Here is the experiment summary:

{json.dumps(summary, ensure_ascii=False, indent=2)}

Return a JSON array of issues found. Each issue must have:
- "path": where the issue is (e.g., "protocol_texts vs temperature")
- "severity": "warning" or "error"
- "category": "coherence"
- "message": short description of the contradiction
- "details": explanation of why this is inconsistent

If everything is coherent, return empty array: []

Return ONLY the JSON array, no markdown, no explanation."""

    try:
        completion = create_chat_completion(
            client,
            model=CHAT_AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        content = completion.choices[0].message.content.strip()

        # Parse the model response into a JSON issue list.
        try:
            issues = json.loads(content)
        except json.JSONDecodeError:
            # Try to extract from code block
            match = re.search(r"```(?:json)?\s*(\[\s*[\s\S]*?\])\s*```", content, re.IGNORECASE)
            if match:
                issues = json.loads(match.group(1))
            else:
                # Try to find array
                start = content.find("[")
                end = content.rfind("]")
                if start != -1 and end > start:
                    issues = json.loads(content[start:end+1])
                else:
                    return [{
                        "path": "",
                        "severity": "warning",
                        "category": "other",
                        "message": "Could not parse semantic coherence response",
                        "validator": "semantic_coherence",
                        "raw": content
                    }]

        # Add validator tag to all issues
        for issue in issues:
            issue["validator"] = "semantic_coherence"

        return issues

    except Exception as e:
        return [{
            "path": "",
            "severity": "error",
            "category": "other",
            "message": f"Semantic coherence validation failed: {str(e)}",
            "validator": "semantic_coherence"
        }]
