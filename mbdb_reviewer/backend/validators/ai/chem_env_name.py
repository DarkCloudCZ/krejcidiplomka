"""
Chemical Environment Name Validator (AI-based)

Checks if chemical environment names accurately describe their constituents using LLM.
Only flags contradictions, not missing information.
Batches all environments into a single LLM call for efficiency.
"""

import json
from typing import Dict, Any, List

from utils.json_utils import find_line_for_path_and_value, parse_llm_json_response
from utils.llm_utils import create_chat_completion, get_chat_ai_client
from config import CHAT_AI_MODEL


def run_chem_env_name_validation(record_json: Dict[str, Any]) -> List[Dict]:
    """
    Check if chemical environment names match their actual constituents.
    Uses LLM to detect contradictions (name says X but actual is Y).

    Batches all environments into a single LLM call for efficiency.
    """
    issues = []
    client = get_chat_ai_client()

    metadata = record_json.get("metadata", {})
    gp = metadata.get("general_parameters", {})
    chem_envs = gp.get("chemical_environments", [])

    if not chem_envs:
        return []

    # Build summary for all environments (batched)
    all_envs_summary = []
    for idx, env in enumerate(chem_envs):
        name = env.get("name", "")
        constituents = env.get("constituents", [])
        solvents = env.get("solvent", []) or []

        if not name and not constituents and not solvents:
            continue

        def _entry(c: Dict[str, Any], location: str, item_index: int) -> Dict[str, Any]:
            conc = c.get("concentration") or {}
            bi = c.get("basic_information") or {}
            bi_title = (bi.get("title") or {}).get("en", "")
            return {
                "item_index": item_index,
                "location": location,
                "name": c.get("name", ""),
                "basic_information_title": bi_title,
                "inchikey": bi.get("id", ""),
                "concentration_value": conc.get("value"),
                "concentration_unit": conc.get("unit", ""),
            }

        constituent_summary = [
            _entry(c, "constituents", i) for i, c in enumerate(constituents)
        ]
        solvent_summary = [
            _entry(s, "solvent", i) for i, s in enumerate(solvents)
        ]

        all_envs_summary.append({
            "index": idx,
            "name": name,
            "constituents": constituent_summary,
            "solvent": solvent_summary,
            "ph": env.get("ph")
        })

    if not all_envs_summary:
        return []

    prompt = f"""You are checking chemical environment metadata for three classes of problem.

CHECK 1 — Environment name vs contents:
  Does the environment NAME contradict the actual constituents?
  - ONLY report if the name states something CONTRADICTORY to actual data
  - Do NOT report if the name simply omits some constituents — that's acceptable
  - Do NOT report if the name is generic like "Buffer" or "PBS"
  Examples of ERRORS to report:
  - Name says "NaCl 150 mM" but actual concentration is 100 mM → WRONG
  - Name says "pH 7.4" but actual pH is 6.8 → WRONG
  - Name mentions "HEPES" but no HEPES in constituents → WRONG
  Examples NOT to report:
  - Name is "PBS" without listing all components → OK (generic name)
  - Name omits BSA that is in constituents → OK (partial name is fine)

CHECK 2 — Constituent name vs basic_information identity:
  Each constituent has a free-text "name" (what the depositor wrote) and a curated
  "basic_information_title" (the official chemical name) plus an "inchikey".
  If the name refers to a clearly DIFFERENT chemical than the basic_information_title,
  flag it. These are two different molecules if their inchikeys differ and the names
  are not synonyms.
  - Example WRONG: name="SDS" but basic_information_title="Sodium Lauryl Sulfoacetate"
    — SDS is sodium dodecyl sulfate (inchikey DBMJMQXJHONAFJ-...), Sodium Lauryl
    Sulfoacetate is a completely different molecule. Flag as identity mismatch.
  - Example OK: name="NaCl" + basic_information_title="Sodium chloride" — same
    compound, abbreviation vs full name.
  - Example OK: name="Tris-HCl" + basic_information_title="Tris(Hydroxymethyl)aminomethane
    Chloride" — same compound.
  Do NOT flag if basic_information_title is empty (nothing to compare against).

CHECK 3 — Solvent vs constituent placement:
  Items with location="solvent" must be a TRUE solvent (water, D2O, DMSO, ethanol,
  methanol, acetonitrile, PEG). If a solvent entry is actually a buffer salt
  (Tris, Tris-HCl, HEPES, MOPS, PBS, phosphate) or any other dissolved chemical
  that belongs in constituents, flag it as misplaced.
  - Example WRONG: solvent entry name="Tris:HCl" at 50 mM — Tris-HCl is a buffer
    constituent, not a solvent. Should be moved to constituents.
  - Example OK: solvent entry name="Water".

Environments to check:
{json.dumps(all_envs_summary, ensure_ascii=False, indent=2)}

Return ONLY a JSON array. Each object must have:
- "index": the environment index (int)
- "check": "name" | "identity" | "placement"
- "location": "constituents" or "solvent" (or null for CHECK 1)
- "item_index": the constituent/solvent index inside that environment (or null for CHECK 1)
- "message": description of the problem

If no errors, return empty array: []
No markdown, just JSON."""

    try:
        completion = create_chat_completion(
            client,
            model=CHAT_AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        content = completion.choices[0].message.content.strip()
        llm_issues = parse_llm_json_response(content)

        json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

        for issue in llm_issues:
            idx = issue.get("index", 0)
            if not isinstance(idx, int) or idx >= len(chem_envs):
                continue

            env = chem_envs[idx]
            env_name = env.get("name", "")
            base_path = f"metadata.general_parameters.chemical_environments[{idx}]"

            location = issue.get("location")
            item_index = issue.get("item_index")
            value_for_line = env_name

            if location in ("constituents", "solvent") and isinstance(item_index, int):
                path = f"{base_path}.{location}[{item_index}]"
                items = env.get(location) or []
                if 0 <= item_index < len(items):
                    value_for_line = items[item_index].get("name", "") or env_name
            else:
                path = base_path

            line = find_line_for_path_and_value(json_pretty, path, value_for_line)

            issues.append({
                "path": path,
                "severity": "warning",
                "category": "cross_field",
                "message": issue.get("message", "Chemical environment problem"),
                "validator": "chem_env_name",
                "value": value_for_line,
                "line": line
            })

    except Exception as e:
        # If LLM fails, return empty - this is advisory validation
        pass

    return issues
