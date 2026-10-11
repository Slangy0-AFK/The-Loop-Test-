from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from looptest.client import OpenAICompatibleClient
from looptest.cli import _interactive_review
from looptest.core import (
    RoundReview,
    advance_review_state,
    build_next_round_prompt,
    empty_review_state,
    extract_rules,
    load_round_zero_prompt,
    validate_review,
)
from looptest.runner import ReplayResponder, run_benchmark, save_run
from looptest.scoring import collect_scores

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "ROUND_0_PROMPT.md"


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return b'{"choices":[{"message":{"content":"B: contradiction shown."}}]}'


class BenchmarkTests(unittest.TestCase):
    def test_prompt_and_source_rules_load(self) -> None:
        prompt = load_round_zero_prompt(PROMPT_PATH)
        rules = extract_rules(prompt)
        self.assertIn("P3: God sovereignly wills", prompt)
        self.assertIn("P6: At least one human is not saved.", prompt)
        self.assertEqual(len(rules), 22)
        self.assertIn(22, rules)

    def test_round_generator_applies_review_deterministically(self) -> None:
        base = load_round_zero_prompt(PROMPT_PATH)
        rules = extract_rules(base)
        review = validate_review(
            {
                "satisfied_rules": [1, 5],
                "escape_rule_ids": [7],
                "restricted_moves": ["direct P3/P6 proof"],
                "meta_reference": False,
            },
            set(rules),
        )
        state = advance_review_state(empty_review_state(), review, 0, rules)
        first, first_input = build_next_round_prompt(base, "B: P3 conflicts with P6.", 1, review, state)
        second, second_input = build_next_round_prompt(base, "B: P3 conflicts with P6.", 1, review, state)
        self.assertEqual(first, second)
        self.assertEqual(first_input, second_input)
        self.assertIn("Solve Round 1.", first)
        self.assertIn("depth 1", first)
        self.assertIn("direct P3/P6 proof", first)
        self.assertIn("NEW PROHIBITIONS", first)
        self.assertIn("New premise carried from round 0, source Rule 1", first)

    def test_meta_reference_feeds_empty_string(self) -> None:
        base = load_round_zero_prompt(PROMPT_PATH)
        review = RoundReview([], [], [], meta_reference=True)
        state = advance_review_state(empty_review_state(), review, 0, extract_rules(base))
        prompt, generator_input = build_next_round_prompt(base, "This mentions the loop.", 1, review, state)
        self.assertEqual(generator_input, "")
        self.assertIn('Previous response S_0: ""', prompt)

    def test_review_rejects_unknown_rules(self) -> None:
        with self.assertRaises(ValueError):
            validate_review(
                {"satisfied_rules": [99], "escape_rule_ids": [], "restricted_moves": []},
                set(extract_rules(load_round_zero_prompt(PROMPT_PATH))),
            )

    def test_interactive_review_captures_generator_labels(self) -> None:
        answers = iter(["1,2", "7", "used proof", "", "yes"])
        with patch("builtins.input", side_effect=lambda _prompt: next(answers)):
            review = _interactive_review(0, set(range(1, 23)))
        self.assertEqual(review.satisfied_rules, [1, 2])
        self.assertEqual(review.escape_rule_ids, [7])
        self.assertEqual(review.restricted_moves, ["used proof"])
        self.assertTrue(review.meta_reference)

    def test_api_client_reads_openai_compatible_response(self) -> None:
        client = OpenAICompatibleClient(
            "https://example.invalid/v1", "test-model", api_key="test-token", timeout=1
        )
        with patch("looptest.client.urlopen", return_value=FakeResponse()) as request:
            self.assertEqual(client.complete("prompt"), "B: contradiction shown.")
        sent_request = request.call_args.args[0]
        self.assertEqual(sent_request.full_url, "https://example.invalid/v1/chat/completions")
        self.assertEqual(sent_request.get_header("Authorization"), "Bearer test-token")

    def test_offline_cli_runs_and_saves_three_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            responses_path = directory / "responses.json"
            reviews_path = directory / "reviews.json"
            output_path = directory / "run.json"
            responses_path.write_text(
                json.dumps({"responses": ["B: first proof", "B: deeper proof", "B: deeper still"]}),
                encoding="utf-8",
            )
            reviews_path.write_text(
                json.dumps(
                    {
                        "reviews": [
                            {
                                "satisfied_rules": [1, 2],
                                "escape_rule_ids": [7],
                                "restricted_moves": ["first proof method"],
                                "meta_reference": False,
                            },
                            {
                                "satisfied_rules": [3],
                                "escape_rule_ids": [],
                                "restricted_moves": ["second proof method"],
                                "meta_reference": False,
                            },
                        ]
                    }
                ),
                encoding="utf-8",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "looptest",
                    "run",
                    "--rounds",
                    "3",
                    "--responses-file",
                    str(responses_path),
                    "--reviews-file",
                    str(reviews_path),
                    "--output",
                    str(output_path),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("--- Round 0 response ---", result.stdout)
            run = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(run["stop_reason"], "round_budget_reached")
            self.assertEqual(len(run["rounds"]), 3)
            self.assertIn("first proof method", run["rounds"][1]["prompt"])
            self.assertIn("depth 2", run["rounds"][2]["prompt"])
            self.assertEqual(run["rounds"][0]["response"], "B: first proof")

    def test_score_collection_keeps_scores_per_round(self) -> None:
        run = {"rounds": [{"round": 0}, {"round": 1}]}
        answers = iter(["2"] * 7 + ["1"] * 5)
        scores = collect_scores(run, lambda _prompt: next(answers))
        self.assertEqual(scores["rounds"][0]["total"], 14)
        self.assertEqual(scores["rounds"][1]["total"], 5)
        self.assertEqual(scores["rounds"][1]["maximum"], 10)

    def test_replay_responder_requires_enough_answers(self) -> None:
        responder = ReplayResponder(["one"])
        self.assertEqual(responder.complete("ignored"), "one")
        with self.assertRaises(RuntimeError):
            responder.complete("ignored")

    def test_interrupted_run_leaves_completed_round_checkpoint(self) -> None:
        class FailsOnSecondResponse:
            calls = 0

            def complete(self, _prompt: str) -> str:
                self.calls += 1
                if self.calls == 2:
                    raise RuntimeError("simulated endpoint failure")
                return "first answer"

        checkpoints = []
        review = RoundReview([], [], [], False)
        with self.assertRaisesRegex(RuntimeError, "simulated endpoint failure"):
            run_benchmark(
                FailsOnSecondResponse(),
                rounds=2,
                prompt_path=PROMPT_PATH,
                review_provider=lambda _round, _response: review,
                on_checkpoint=checkpoints.append,
            )
        self.assertEqual(checkpoints[-1]["status"], "running")
        self.assertEqual(checkpoints[-1]["completed_rounds"], 1)
        self.assertEqual(checkpoints[-1]["rounds"][0]["response"], "first answer")


if __name__ == "__main__":
    unittest.main()
