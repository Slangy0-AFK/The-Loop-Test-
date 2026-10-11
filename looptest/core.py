from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

GENERATOR_VERSION = "human-reviewed-v1"
RULE_PATTERN = re.compile(r"^RULE\s+(\d+):\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class RoundReview:
    satisfied_rules: list[int]
    escape_rule_ids: list[int]
    restricted_moves: list[str]
    meta_reference: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any], rule_ids: set[int]) -> "RoundReview":
        if not isinstance(value, dict):
            raise ValueError("each review entry must be a JSON object")
        satisfied = _rule_id_list(value.get("satisfied_rules", []), "satisfied_rules", rule_ids)
        escapes = _rule_id_list(value.get("escape_rule_ids", []), "escape_rule_ids", rule_ids)
        moves_value = value.get("restricted_moves", [])
        if not isinstance(moves_value, list) or any(not isinstance(move, str) for move in moves_value):
            raise ValueError("restricted_moves must be a list of strings")
        moves = [move.strip() for move in moves_value if move.strip()]
        if any(len(move) > 500 for move in moves):
            raise ValueError("each restricted move must be 500 characters or fewer")
        meta_reference = value.get("meta_reference", False)
        if not isinstance(meta_reference, bool):
            raise ValueError("meta_reference must be true or false")
        return cls(satisfied, escapes, moves, meta_reference)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _rule_id_list(value: Any, name: str, valid_ids: set[int]) -> list[int]:
    if not isinstance(value, list) or any(type(item) is not int for item in value):
        raise ValueError(f"{name} must be a list of rule numbers")
    if len(value) != len(set(value)):
        raise ValueError(f"{name} cannot contain duplicate rule numbers")
    unknown = set(value) - valid_ids
    if unknown:
        raise ValueError(f"{name} contains unknown rules: {sorted(unknown)}")
    return sorted(value)


def extract_round_zero_prompt(markdown: str) -> str:
    match = re.search(r"```text\s*\n(.*?)\n```", markdown, flags=re.DOTALL)
    if not match:
        raise ValueError("Round 0 prompt file must contain a fenced text block")
    return match.group(1).strip()


def load_round_zero_prompt(path: Path) -> str:
    return extract_round_zero_prompt(path.read_text(encoding="utf-8"))


def extract_rules(prompt: str) -> dict[int, str]:
    rules = {int(number): text.strip() for number, text in RULE_PATTERN.findall(prompt)}
    if not rules:
        raise ValueError("No numbered RULE entries found in the Round 0 prompt")
    return rules


def validate_review(value: dict[str, Any], rule_ids: set[int]) -> RoundReview:
    return RoundReview.from_dict(value, rule_ids)


def advance_review_state(
    state: dict[str, list[dict[str, Any]]],
    review: RoundReview,
    source_round: int,
    rule_texts: dict[int, str],
) -> dict[str, list[dict[str, Any]]]:
    next_state = {key: list(items) for key, items in state.items()}
    for rule_id in review.satisfied_rules:
        next_state["premises"].append(
            {"round": source_round, "rule_id": rule_id, "text": rule_texts[rule_id]}
        )
    for rule_id in review.escape_rule_ids:
        next_state["prohibitions"].append(
            {"round": source_round, "rule_id": rule_id, "text": rule_texts[rule_id]}
        )
    for move in review.restricted_moves:
        next_state["restricted_moves"].append({"round": source_round, "text": move})
    return next_state


def empty_review_state() -> dict[str, list[dict[str, Any]]]:
    return {"premises": [], "prohibitions": [], "restricted_moves": []}


def build_next_round_prompt(
    base_prompt: str,
    previous_response: str,
    next_round: int,
    review: RoundReview,
    state: dict[str, list[dict[str, Any]]],
) -> tuple[str, str]:
    if next_round < 1:
        raise ValueError("next_round must be at least 1")
    source_response = "" if review.meta_reference else previous_response
    round_zero_end = "Solve Round 0."
    if round_zero_end not in base_prompt:
        raise ValueError("Round 0 prompt must end with 'Solve Round 0.'")
    prompt_prefix = base_prompt.rsplit(round_zero_end, 1)[0].rstrip()

    additions: list[str] = []
    if state["premises"]:
        additions.extend(
            f'- New premise carried from round {item["round"]}, source Rule {item["rule_id"]}: {item["text"]}'
            for item in state["premises"]
        )
    else:
        additions.append("- None")
    premises = "\n".join(additions)

    prohibitions = "\n".join(
        f'- New prohibition from round {item["round"]}, based on source Rule {item["rule_id"]}: {item["text"]}'
        for item in state["prohibitions"]
    ) or "- None"
    restricted_moves = "\n".join(
        f'- Round {item["round"]}: {item["text"]}' for item in state["restricted_moves"]
    ) or "- None"

    previous_json = json.dumps(source_response, ensure_ascii=True)
    overlay = f"""\n\nSANDBOX ROUND {next_round} STATE

The previous response is the only response content supplied to this round generator. Its exact value is the JSON string below. An empty string means the evaluator marked the prior response as referencing the rules, the loop, the generator, or the meta-level.
Previous response S_{next_round - 1}: {previous_json}

ADDED PREMISES
{premises}

NEW PROHIBITIONS
{prohibitions}

RESTRICTED MOVES
{restricted_moves}

For this round, provide the required (A) or (B) result and validation layers to depth {next_round}. Each layer must use classical first-order logic and satisfy the supplied constraints. Do not reuse a restricted move.

Solve Round {next_round}."""
    return f"{prompt_prefix}\n\n{overlay}", source_response
