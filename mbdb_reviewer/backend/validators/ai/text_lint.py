"""
AI text-quality validator.

It checks text fields for spelling and grammar issues. Sequence-specific
alphabet validation still lives in the deterministic rule validator, but the
prompt keeps a safety rule so the model does not invent sequence fixes.
"""

import json
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

from utils.json_utils import iter_text_nodes, find_line_for_path_and_value, parse_llm_json_response
from utils.llm_utils import create_chat_completion, get_chat_ai_client
from config import CHAT_AI_MODEL, CHUNK_SIZE, TEXT_LINT_MAX_WORKERS


def _build_text_lint_prompt(text_nodes: List[Dict]) -> str:
    """Build the prompt for text lint LLM request."""
    return f"""You are a text quality reviewer for scientific database records.

You receive text snippets from an MBDB JSON record. Each item has:
- "path": the exact JSON path
- "text": the string value

Find spelling errors, grammar mistakes, and language issues.

RULES:
1. Only report issues in "text" values
2. Copy paths exactly - do NOT modify them
3. Focus on: typos, misspellings, grammatical errors
4. DO NOT flag valid scientific terms or chemical names spelled correctly
5. DO flag obvious typos even in chemical/scientific names (e.g., "Pluoronic" should be "Pluronic", "sodim" should be "sodium", "Sodium chlorid" should be "Sodium chloride", "Sodium hydroxid" should be "Sodium hydroxide" — watch for missing trailing letters like "chlorid"/"hydroxid"/"lipas")
6. Ignore: UUIDs, URLs, identifiers, file paths
7. BIOLOGICAL SEQUENCES (protein/DNA/RNA): If a path ends in ".sequence" or the
   text is a long run of single letters with no spaces (likely an amino-acid or
   nucleotide sequence), flag any invalid characters (digits, punctuation,
   non-IUPAC letters, Unicode noise like "ř", "#", "*", "^", "@", ":", "+").
   For sequences, ALWAYS set "suggested_fix" to the empty string "". Do NOT
   attempt to clean, rewrite, or reconstruct the sequence — you cannot know the
   correct residues. The message should say to verify the sequence against the
   original source (UniProt, PDB, GenBank, etc.).

SEVERITY GUIDE:
- Use "error" for clear typos and misspellings (e.g., "addtional", "Substraction", "mixded")
- Use "warning" for style/notation preferences, less common but understandable terms, and
  capitalization variants (e.g., "kOff" vs "k_off", "Degassation" vs "Degassing",
  "Nanotemper" vs "NanoTemper", "dH" vs "ΔH")

Input:
{json.dumps(text_nodes, ensure_ascii=False, indent=2)}

Return ONLY a JSON array. Each object must have:
- "path": exact path from input
- "severity": "error" or "warning"
- "message": short description
- "value": the original text with error
- "suggested_fix": the corrected text

If no issues, return []. No markdown, just JSON."""


def _process_text_lint_chunk(client: OpenAI, chunk: List[Dict]) -> List[Dict]:
    """Process a single chunk of text nodes through the LLM."""
    prompt = _build_text_lint_prompt(chunk)

    completion = create_chat_completion(
        client,
        model=CHAT_AI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,
    )

    content = completion.choices[0].message.content.strip()
    return parse_llm_json_response(content)


def run_ai_text_lint_parallel(record_json: Dict[str, Any]) -> List[Dict]:
    """Extract text leaves and validate them in parallel LLM chunks."""
    client = get_chat_ai_client()
    text_nodes = list(iter_text_nodes(record_json))

    if not text_nodes:
        return []

    json_pretty = json.dumps(record_json, ensure_ascii=False, indent=2)

    seen_texts: Dict[str, Dict] = {}
    for node in text_nodes:
        text = node.get("text", "")
        if text not in seen_texts:
            seen_texts[text] = node

    unique_nodes = list(seen_texts.values())

    chunks = [unique_nodes[i:i + CHUNK_SIZE] for i in range(0, len(unique_nodes), CHUNK_SIZE)]

    all_issues: List[Dict] = []

    with ThreadPoolExecutor(max_workers=TEXT_LINT_MAX_WORKERS) as executor:
        future_to_chunk = {
            executor.submit(_process_text_lint_chunk, client, chunk): i
            for i, chunk in enumerate(chunks)
        }

        for future in as_completed(future_to_chunk):
            try:
                chunk_issues = future.result()
                all_issues.extend(chunk_issues)
            except Exception as e:
                print(f"Text lint chunk failed: {e}")

    for issue in all_issues:
        path = issue.get('path', '')
        value = issue.get('value', '')
        line = find_line_for_path_and_value(json_pretty, path, value)
        issue['line'] = line

    return all_issues
