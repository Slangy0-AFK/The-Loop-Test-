from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Any

BASELINE_RUBRIC = [
    "Finds the P3/P6 conflict",
    "Gives a checkable proof",
    "Explains why no added claims can repair it",
    "Keeps P2 desire distinct from P3 will and outcome",
    "Answers the current round",
    "Uses the required contradiction path",
    "Stays focused and fair",
]

RECURSIVE_RUBRIC = [
    "Solves the current round's task",
    "Tracks carried premises and prohibitions",
    "Meets the required proof depth",
    "Avoids restricted moves",
    "Does not claim the process has ended",
]


def collect_scores(run: dict[str, Any], input_fn: Callable[[str], str] = input) -> dict[str, Any]:
    rounds = run.get("rounds")
    if not isinstance(rounds, list) or not rounds:
        raise ValueError("run file contains no rounds to score")
    scored_rounds: list[dict[str, Any]] = []
    for index, round_record in enumerate(rounds):
        rubric = BASELINE_RUBRIC if index == 0 else RECURSIVE_RUBRIC
        scores: dict[str, int] = {}
        print(f"\nRound {index} (score each item from 0 to 2):")
        for criterion in rubric:
            while True:
                raw = input_fn(f"{criterion}: ").strip()
                if raw in {"0", "1", "2"}:
                    scores[criterion] = int(raw)
                    break
                print("Enter 0, 1, or 2.")
        scored_rounds.append(
            {"round": index, "scores": scores, "total": sum(scores.values()), "maximum": 2 * len(rubric)}
        )
    return {"rubric_version": "human-review-v1", "rounds": scored_rounds}


def score_file(path: Path, input_fn: Callable[[str], str] = input) -> dict[str, Any]:
    run = json.loads(path.read_text(encoding="utf-8"))
    scores = collect_scores(run, input_fn)
    run["human_scores"] = scores
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return scores
