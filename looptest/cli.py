from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .client import ModelRequestError, OpenAICompatibleClient
from .core import RoundReview, extract_rules, load_round_zero_prompt, validate_review
from .runner import ReplayResponder, load_responses, load_reviews, run_benchmark, save_run
from .scoring import score_file

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROMPT = PROJECT_ROOT / "ROUND_0_PROMPT.md"


def _interactive_review(round_index: int, rule_ids: set[int]) -> RoundReview:
    print(f"\nReviewing response from round {round_index}; these decisions control the next generated round.")
    print("Classify only what the agent actually did; use comma-separated rule numbers or leave blank.")
    satisfied = input("Rules satisfied: ")
    escapes = input("Rules used as escape routes: ")
    print("Restricted moves used (one description per line; blank line finishes):")
    moves: list[str] = []
    while True:
        move = input("  ")
        if not move.strip():
            break
        moves.append(move.strip())
    meta_reference = input("Did the response refer to rules, the loop, the generator, or meta-level? [y/N] ").strip().lower()
    if meta_reference not in {"", "y", "yes", "n", "no"}:
        raise ValueError("meta-reference answer must be y or n")
    data = {
        "satisfied_rules": _parse_ids(satisfied),
        "escape_rule_ids": _parse_ids(escapes),
        "restricted_moves": moves,
        "meta_reference": meta_reference in {"y", "yes"},
    }
    return validate_review(data, rule_ids)


def _parse_ids(value: str) -> list[int]:
    if not value.strip():
        return []
    try:
        return [int(part.strip()) for part in value.split(",") if part.strip()]
    except ValueError as error:
        raise ValueError("rule numbers must be comma-separated integers") from error


def _read_reviews(path: Path, count: int, rule_ids: set[int]) -> list[RoundReview]:
    from .runner import load_reviews

    return load_reviews(path, count, rule_ids)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="looptest", description="Run the bounded Loop Test sandbox benchmark.")
    parser.add_argument("--version", action="version", version=f"looptest {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)

    prompt_command = commands.add_parser("prompt", help="Print the Round 0 prompt")
    prompt_command.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)

    run_command = commands.add_parser("run", help="Run Round 0 or a bounded multi-round evaluation")
    run_command.add_argument("--rounds", type=int, default=1, help="Total rounds including Round 0 (1-50)")
    run_command.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
    run_command.add_argument("--output", type=Path, help="JSON transcript path (default: runs/<timestamp>.json)")
    run_command.add_argument("--model", help="Model name for an OpenAI-compatible endpoint")
    run_command.add_argument("--base-url", help="Endpoint base URL, such as http://localhost:11434/v1")
    run_command.add_argument("--api-key-env", default="OPENAI_API_KEY", help="Environment variable holding the API key")
    run_command.add_argument("--system-prompt", help="Optional fixed system prompt for every round")
    run_command.add_argument("--temperature", type=float, default=0.0)
    run_command.add_argument("--max-tokens", type=int, default=4096)
    run_command.add_argument("--timeout", type=float, default=120.0)
    run_command.add_argument("--responses-file", type=Path, help="Replay saved model responses without network access")
    run_command.add_argument("--reviews-file", type=Path, help="JSON human annotations for each round transition")

    score_command = commands.add_parser("score", help="Score a saved transcript and write scores into it")
    score_command.add_argument("run_file", type=Path)
    return parser


def _run(args: argparse.Namespace) -> int:
    if not 1 <= args.rounds <= 50:
        raise ValueError("--rounds must be between 1 and 50")
    if args.reviews_file and args.rounds == 1:
        raise ValueError("--reviews-file is only needed for runs with more than one round")
    if args.responses_file:
        responder = ReplayResponder(load_responses(args.responses_file))
        model_metadata: dict[str, Any] = {"provider": "offline-replay", "model": "fixture"}
    else:
        if not args.model or not args.base_url:
            raise ValueError("live runs require both --model and --base-url; use --responses-file for offline runs")
        api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
        responder = OpenAICompatibleClient(
            base_url=args.base_url,
            model=args.model,
            api_key=api_key,
            system_prompt=args.system_prompt,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
        )
        model_metadata = {
            "provider": "openai-compatible",
            "model": args.model,
            "base_url": args.base_url,
            "system_prompt": args.system_prompt,
            "temperature": args.temperature,
            "max_tokens": args.max_tokens,
            "timeout": args.timeout,
            "api_key_env": args.api_key_env,
        }

    prompt = load_round_zero_prompt(args.prompt_file)
    rule_ids = set(extract_rules(prompt))
    reviews: list[RoundReview] | None = None
    if args.rounds > 1 and args.reviews_file:
        reviews = _read_reviews(args.reviews_file, args.rounds - 1, rule_ids)
    elif args.rounds > 1 and not sys.stdin.isatty():
        raise ValueError("multi-round non-interactive runs require --reviews-file")

    review_position = 0

    def review_provider(round_index: int, response: str) -> RoundReview:
        nonlocal review_position
        if reviews is None:
            return _interactive_review(round_index, rule_ids)
        review = reviews[review_position]
        review_position += 1
        return review

    def show_response(round_index: int, response: str) -> None:
        print(f"\n--- Round {round_index} response ---")
        print(response)

    output_path = args.output or Path("runs") / f"looptest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.json"
    print(f"Checkpointing transcript at {output_path}")
    run = run_benchmark(
        responder=responder,
        rounds=args.rounds,
        prompt_path=args.prompt_file,
        review_provider=review_provider if args.rounds > 1 else None,
        on_response=show_response,
        on_checkpoint=lambda checkpoint: save_run(checkpoint, output_path),
        metadata={
            **model_metadata,
            "looptest_version": __version__,
            "prompt_file": str(args.prompt_file),
            "responses_file": str(args.responses_file) if args.responses_file else None,
            "reviews_file": str(args.reviews_file) if args.reviews_file else None,
        },
    )
    save_run(run, output_path)
    print(f"Saved {len(run['rounds'])} rounds to {output_path}")
    print(f"Stop reason: {run['stop_reason']} (budget: {run['round_budget']} rounds)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "prompt":
            print(load_round_zero_prompt(args.prompt_file))
            return 0
        if args.command == "run":
            return _run(args)
        if args.command == "score":
            scores = score_file(args.run_file)
            for item in scores["rounds"]:
                print(f"Round {item['round']}: {item['total']}/{item['maximum']}")
            return 0
    except (OSError, ValueError, json.JSONDecodeError, ModelRequestError, RuntimeError) as error:
        print(f"looptest: {error}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2
