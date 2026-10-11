from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from . import __version__
from .core import (
    GENERATOR_VERSION,
    RoundReview,
    advance_review_state,
    build_next_round_prompt,
    empty_review_state,
    extract_rules,
    load_round_zero_prompt,
)


class Responder(Protocol):
    def complete(self, prompt: str) -> str: ...


ReviewProvider = Callable[[int, str], RoundReview]
ResponseObserver = Callable[[int, str], None]
CheckpointWriter = Callable[[dict[str, Any]], None]


class ReplayResponder:
    def __init__(self, responses: list[str]) -> None:
        if not responses or any(not isinstance(response, str) for response in responses):
            raise ValueError("responses file must contain a non-empty list of strings")
        self.responses = responses
        self.position = 0

    def complete(self, prompt: str) -> str:
        del prompt
        if self.position >= len(self.responses):
            raise RuntimeError("responses file has fewer entries than the requested rounds")
        response = self.responses[self.position]
        self.position += 1
        return response


def load_responses(path: Path) -> list[str]:
    value = json.loads(path.read_text(encoding="utf-8"))
    responses = value.get("responses") if isinstance(value, dict) else value
    if not isinstance(responses, list) or any(not isinstance(item, str) for item in responses):
        raise ValueError("responses file must be a JSON list of strings or an object with a 'responses' list")
    return responses


def load_reviews(path: Path, expected_count: int, rule_ids: set[int]) -> list[RoundReview]:
    value = json.loads(path.read_text(encoding="utf-8"))
    reviews = value.get("reviews") if isinstance(value, dict) else value
    if not isinstance(reviews, list):
        raise ValueError("reviews file must be a JSON list or an object with a 'reviews' list")
    if len(reviews) != expected_count:
        raise ValueError(f"expected {expected_count} transition reviews, found {len(reviews)}")
    if any(not isinstance(item, dict) for item in reviews):
        raise ValueError("each review entry must be a JSON object")
    return [RoundReview.from_dict(item, rule_ids) for item in reviews]


def run_benchmark(
    responder: Responder,
    rounds: int,
    prompt_path: Path,
    review_provider: ReviewProvider | None = None,
    metadata: dict[str, Any] | None = None,
    on_response: ResponseObserver | None = None,
    on_checkpoint: CheckpointWriter | None = None,
) -> dict[str, Any]:
    if not 1 <= rounds <= 50:
        raise ValueError("rounds must be between 1 and 50")
    base_prompt = load_round_zero_prompt(prompt_path)
    rule_texts = extract_rules(base_prompt)
    current_prompt = base_prompt
    state = empty_review_state()
    run: dict[str, Any] = {
        "schema_version": 1,
        "generator_version": GENERATOR_VERSION,
        "run_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
        "stop_reason": None,
        "round_budget": rounds,
        "completed_rounds": 0,
        "metadata": metadata or {},
        "rounds": [],
    }
    if on_checkpoint is not None:
        on_checkpoint(run)

    for round_index in range(rounds):
        response = responder.complete(current_prompt)
        if not isinstance(response, str):
            raise RuntimeError("responder returned a non-text response")
        if on_response is not None:
            on_response(round_index, response)
        record: dict[str, Any] = {
            "round": round_index,
            "prompt": current_prompt,
            "response": response,
            "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
        }
        run["rounds"].append(record)
        run["completed_rounds"] = len(run["rounds"])
        if on_checkpoint is not None:
            on_checkpoint(run)

        if round_index == rounds - 1:
            continue
        if review_provider is None:
            raise ValueError("multi-round runs require a human review provider")
        review = review_provider(round_index, response)
        if not isinstance(review, RoundReview):
            raise TypeError("review provider must return a RoundReview")
        record["review"] = review.to_dict()
        state = advance_review_state(state, review, round_index, rule_texts)
        current_prompt, generator_input = build_next_round_prompt(
            base_prompt=base_prompt,
            previous_response=response,
            next_round=round_index + 1,
            review=review,
            state=state,
        )
        record["generator_input"] = generator_input
        record["next_prompt_sha256"] = hashlib.sha256(current_prompt.encode("utf-8")).hexdigest()
        if on_checkpoint is not None:
            on_checkpoint(run)

    run["status"] = "completed"
    run["stop_reason"] = "round_budget_reached"
    if on_checkpoint is not None:
        on_checkpoint(run)
    return run


def save_run(run: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
