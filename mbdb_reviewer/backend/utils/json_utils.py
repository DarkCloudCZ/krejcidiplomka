"""Utility functions for JSON extraction and path manipulation."""
import json
import re
from typing import Any, Dict, Iterator, List, Optional


def iter_text_nodes(obj: Any, path: str = "") -> Iterator[Dict[str, str]]:
    """
    Yield dicts with path/text for every string leaf in the JSON.
    Paths use dot notation for objects and [i] for array indices.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            yield from iter_text_nodes(v, new_path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_path = f"{path}[{i}]"
            yield from iter_text_nodes(v, new_path)
    elif isinstance(obj, str):
        yield {"path": path, "text": obj}


def iter_numeric_nodes(obj: Any, path: str = "") -> Iterator[Dict]:
    """
    Yield dicts with path/value/unit/context for every numeric leaf in the JSON.
    Handles both standalone numbers and {value, unit} objects.
    """
    if isinstance(obj, dict):
        # Check for value+unit pattern (common in MBDB)
        if "value" in obj and isinstance(obj.get("value"), (int, float)):
            context_key = path.split(".")[-1] if path else ""
            yield {
                "path": path,
                "value": obj["value"],
                "unit": obj.get("unit"),
                "context_key": context_key
            }
            return  # Don't recurse deeper into this object

        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            yield from iter_numeric_nodes(v, new_path)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            new_path = f"{path}[{i}]"
            yield from iter_numeric_nodes(v, new_path)
    elif isinstance(obj, (int, float)) and not isinstance(obj, bool):
        # Extract context from path (last key name)
        path_parts = path.replace(']', '').replace('[', '.').split('.')
        context_key = path_parts[-1] if path_parts else ""
        yield {
            "path": path,
            "value": obj,
            "unit": None,
            "context_key": context_key
        }


def find_line_for_path_and_value(json_str: str, path: str, value: str) -> Optional[int]:
    """
    Find line number for a path/value pair in pretty-printed JSON.

    Two-pass value lookup:
    1. Exact quoted match — finds short complete string values (e.g. a name
       field) including their surrounding quotes. Uses ensure_ascii=False so
       non-ASCII characters like 'ř' match the pretty-printed JSON (which is
       dumped with ensure_ascii=False throughout the codebase).
    2. Unquoted substring match — for long values (>=10 chars) we strip the
       outer quotes so a prefix like sequence[:50] can still land on the right
       line inside a longer string literal. The length gate prevents false
       positives on short generic tokens.

    If both value searches fail, falls back to the first occurrence of the
    last key in the path (existing behaviour).
    """
    lines = json_str.split('\n')

    # Pass 1: exact quoted match (ensure_ascii=False so unicode is literal).
    if value:
        value_quoted = json.dumps(value, ensure_ascii=False)
        for idx, line in enumerate(lines, start=1):
            if value_quoted in line:
                return idx

        # Pass 2: unquoted substring match for long/prefix values.
        value_inner = value_quoted
        if value_inner.startswith('"') and value_inner.endswith('"'):
            value_inner = value_inner[1:-1]
        if value_inner and len(value_inner) >= 10:
            for idx, line in enumerate(lines, start=1):
                if value_inner in line:
                    return idx

    # Fallback: find the last key in path.
    path_parts = path.replace(']', '').replace('[', '.').split('.')
    path_parts = [p for p in path_parts if p and not p.isdigit()]

    if path_parts:
        last_key = path_parts[-1]
        for idx, line in enumerate(lines, start=1):
            if f'"{last_key}"' in line:
                return idx
    return None


def build_numeric_line_map(json_str: str, numeric_nodes: List[Dict]) -> Dict[str, int]:
    """
    Build a mapping of JSON paths to line numbers for numeric values.
    Tracks occurrences of each key to handle multiple values with same key name.
    """
    lines = json_str.split('\n')
    path_to_line: Dict[str, int] = {}
    seen_keys: Dict[str, int] = {}  # Track how many times we've seen each key

    for node in numeric_nodes:
        path = node["path"]

        # Extract the last key in path (e.g., "concentration" from "...constituents[0].concentration")
        path_parts = path.replace(']', '').replace('[', '.').split('.')
        path_parts = [p for p in path_parts if p and not p.isdigit()]
        last_key = path_parts[-1] if path_parts else ""

        if not last_key:
            continue

        # Track which occurrence of this key we're looking for
        key_pattern = f'"{last_key}":'
        occurrence = seen_keys.get(key_pattern, 0)

        # Find the nth occurrence of this key pattern in the JSON
        count = 0
        for idx, line in enumerate(lines, start=1):
            if key_pattern in line:
                if count == occurrence:
                    path_to_line[path] = idx
                    break
                count += 1

        seen_keys[key_pattern] = occurrence + 1

    return path_to_line


def parse_llm_json_response(content: str) -> List[Dict]:
    """
    Parse LLM response, handling markdown code blocks and other formatting.
    """
    # 1) Try direct parse
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2) Try extracting from markdown code block
    match = re.search(
        r"```(?:json)?\s*(\[\s*[\s\S]*?\])\s*```",
        content,
        re.IGNORECASE,
    )
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass

    # 3) Try finding array in text
    start = content.find("[")
    end = content.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except Exception:
            pass

    # 4) Fallback - return error
    return [{
        "path": "",
        "severity": "warning",
        "message": "Model returned non-JSON output",
        "value": "",
        "suggested_fix": "",
        "raw": content,
    }]
