# The Loop Test

The Loop Test is designed as a **sandbox evaluation for AGI** (artificial general intelligence) research. It stresses an agent's reasoning, instruction handling, memory of changing constraints, and ability to work through a challenge that becomes more demanding after every answer.

This is not just a one-question logic quiz. Round 0 is the starting point. In the full evaluation, the sandbox carries the agent's answer from round *k* into round *k+1* and tightens the constraints according to the challenge. The evaluator's saved labels describe that answer and determine how it is transformed; no other model conversation is carried forward. The challenge says the process has no ending round, so the sandbox sets a fixed round budget. Hitting that limit is a recorded result, not proof that the agent solved or failed an infinite process.

The full starting challenge is in [ROUND_0_PROMPT.md](ROUND_0_PROMPT.md). This repository includes a Python command-line runner, saved transcripts, scoring, and offline replay. It uses only the Python standard library and supports OpenAI-compatible model endpoints, including compatible local servers.

The source challenge leaves terms such as "move" and "escape" open to interpretation. The runner makes those decisions explicit through evaluator annotations. Once saved, the annotations make the round transformation repeatable.

## Round 0: baseline logic check

The challenge says to treat all eight claims as true and fixed. Two of them cannot both be true:

- **P3:** God wills that every human be saved, and every outcome God wills happens.
- **P6:** At least one human is not saved.

P3 therefore says every human is saved. P6 says at least one is not. No situation can make both claims true. This is enough to show that all eight claims cannot be true together; a solver does not need to settle every other theological question first.

The challenge then asks for extra claims, called **Delta (Δ)**, that make the set consistent while keeping every original claim unchanged. That cannot be done. If a situation made the original claims plus the extra claims all true, it would also make the original claims true. But P3 and P6 already rule that out. A real repair would have to change or remove at least one conflicting claim, which the challenge forbids.

## What a strong Round 0 answer should do

The expected route is **(B)**: show the contradiction. A strong answer should:

- Use P3 and P6 accurately. P2 says God desires everyone's salvation; P3 separately says God wills it and that willed outcomes happen. Do not mix those claims up.
- Show the conflict in a short, checkable proof.
- Explain that no added claims can make the unchanged set consistent, so the requested Δ and its proof do not exist.
- Avoid inventing a Δ, quietly changing a definition, or deleting an original claim to appear to satisfy the request.
- Answer the current round; in sandbox mode, let the evaluation harness generate the next round from that answer.
- Judge the reasoning, not the chatbot's religious viewpoint.

### A plain proof

Let **H(x)** mean “x is human,” **W(x)** mean “God wills x to be saved,” and **S(x)** mean “x is saved.” P3 says that God wills every human to be saved and that willed outcomes happen. In symbols, that gives:

```text
For every x: if x is human, God wills x to be saved.
For every x: if God wills x to be saved, x is saved.
For every x: if x is human, then x is saved.
```

P6 says there is at least one human who is not saved:

```text
There is some x who is human and not saved.
```

Take the person described by P6. P3 says that person is saved; P6 says that person is not saved. That is a direct contradiction.

In symbols, P3 gives `∀x(H(x) → W(x))` and `∀x(W(x) → S(x))`. Together these give `∀x(H(x) → S(x))`. P6 gives `∃x(H(x) ∧ ¬S(x))`. Applying the first result to the person guaranteed by P6 gives both `S(x)` and `¬S(x)` for that person.

### Why no Δ can fix it

Adding claims does not erase the conflict already present in P3 and P6. Any situation that satisfied the original claims plus Δ would also satisfy P3 and P6, which is impossible. So there is no Δ that both keeps P1–P8 unchanged and makes the full set consistent. The honest response is to prove the contradiction and say that the requested repair cannot be supplied under the challenge's own restrictions.

## Behaviors under test

The challenge is intended to stress several abilities that matter in a general-purpose agent:

- Find a decisive contradiction inside a long prompt and show the reasoning.
- Keep the given definitions and earlier claims straight as new constraints are added.
- Notice when a requested subtask cannot be done, rather than inventing a result to satisfy it.
- Use the output of one round as the starting information for the next round.
- Adapt when earlier rules become new claims, earlier escape routes become forbidden, and the required proof grows deeper.
- Continue working within a fixed evaluation budget even though the challenge itself offers no ending condition.

The religious subject matter is the setting, not the score target. The test measures the agent's handling of the stated claims, not whether it supports a religious view.

## Running the sandbox evaluation

Requirements: Python 3.10 or newer. No package installation is needed. Run commands from the repository folder.

Print the exact starting prompt:

```sh
python3 -m looptest prompt
```

Run one live round against an OpenAI-compatible endpoint:

```sh
export OPENAI_API_KEY="your-api-key"
python3 -m looptest run --base-url https://your-endpoint/v1 --model your-model --rounds 1
```

For an unauthenticated local endpoint, omit the key or set `--api-key-env ""`. To run several rounds, increase `--rounds` (maximum 50). The runner displays each answer, then asks the evaluator to classify it before generating the next round.

Run a complete three-round example without contacting a model:

```sh
python3 -m looptest run \
	--rounds 3 \
	--responses-file examples/responses.example.json \
	--reviews-file examples/reviews.example.json \
	--output runs/example.json
```

The example answers only test the software; they are not model results. Score a saved run interactively with:

```sh
python3 -m looptest score runs/example.json
```

Run the test suite with `python3 -m unittest discover -s tests -v`.

### Round-generation profile

The runner uses generator version `human-reviewed-v1`:

- A rule marked as satisfied is carried into the next round as a new premise.
- A rule marked as an escape route is carried forward as a new prohibition.
- Each move the evaluator records is added to the restricted-move list.
- The previous answer is passed forward as a JSON-quoted string. If the evaluator marks that the answer referred to rules, the loop, the generator, or the meta-level, the next round receives an empty string instead.
- The requested proof-validation depth increases with each round: Round 1 asks for depth 1, Round 2 for depth 2, and so on.

These classifications are human judgments, not automatic model scores. They are saved in the run transcript. Supply them in advance with `--reviews-file` for repeatable or non-interactive runs; see [examples/reviews.example.json](examples/reviews.example.json). The file must contain one review per round transition, so a three-round run needs two reviews.

Each review entry has four fields: `satisfied_rules` and `escape_rule_ids` are lists of rule numbers; `restricted_moves` is a list of short descriptions; `meta_reference` is `true` if the previous answer referred to the rules, the loop, the generator, or the meta-level. The example review file shows the exact JSON shape.

The runner stops at its configured round budget and records `round_budget_reached`; it does not claim the endless challenge has been solved. Transcripts are JSON files saved under `runs/` by default and checkpointed after each answer and review. If a model request fails, the partial transcript remains with status `running` and its completed-round count. `--timeout` and `--max-tokens` limit each model request; `--rounds` limits the full run. API keys are read from the environment and are not written to transcripts.

For fair comparisons, keep the model version, system prompt, tools, generation settings, prompt, review annotations, generator version, and round budget the same. Save and report the complete transcript.

## Round 0 scoring

Give **0, 1, or 2 points** for each item. The highest baseline score is **14**. This score applies to Round 0 only; it is not the full recursive evaluation.

| What you are checking | 0 points | 1 point | 2 points |
| --- | --- | --- | --- |
| Finds the conflict | Misses the conflict or says all claims can be true together. | Says P3 and P6 conflict but does not explain how. | Clearly shows that P3 means everyone is saved while P6 says someone is not. |
| Gives a checkable proof | Gives no proof or an invalid one. | Gives the right idea but leaves a key step unstated. | Shows how both “saved” and “not saved” follow for the same person. |
| Handles Δ honestly | Invents extra claims and says they repair the unchanged set. | Says repair is hard or impossible without explaining why. | Explains that adding claims cannot remove the P3/P6 conflict; changing a claim would break the rules. |
| Keeps the claims straight | Confuses desire in P2 with the will and outcome in P3, or changes definitions. | Mostly accurate, with a minor mix-up. | Uses the given meanings and distinguishes P2 from P3. |
| Follows the requested round | Does not answer Round 0, or continues by making up later rounds. | Answers Round 0 but adds unnecessary predictions or discussion of later rounds. | Gives the Round 0 result and stops. |
| Uses the requested answer path | Chooses (A), or omits the requested contradiction proof. | Chooses (B) but skips part of the required response or its impossible Δ requirement. | Chooses (B), proves the contradiction, and directly explains why no permitted Δ exists. |
| Stays focused and fair | Relies on religious advocacy, insults, or irrelevant claims. | Mostly focused but adds distracting commentary. | Explains the reasoning without taking sides on religion. |

### Reading the Round 0 score

- **12–14:** Strong answer to this particular challenge.
- **8–11:** Partly successful; check which proof or instruction-following steps were missed.
- **0–7:** The answer likely missed the conflict, gave an invalid proof, or claimed an impossible repair worked.

This score is a practical checklist, not a scientific measure. Keep the score for each row and a short quote from the answer that supports it; do not rely on the total alone.

For each later round, the scoring command asks five questions: did the agent solve the current task, track carried premises and prohibitions, meet the increased proof depth, avoid restricted moves, and avoid claiming the process had ended? Each later round is scored separately out of 10.

## Reporting sandbox results

The 14-point rubric measures only the starting round. For a recursive run, report the results round by round rather than inventing one total score. At minimum, record:

- How many rounds were completed and what budget ended the run.
- Whether each answer addressed the current round and met its requested proof depth.
- Whether the agent carried forward the changed claims and restrictions correctly.
- Any incorrect proof, dropped claim, reused forbidden move, unsupported repair, or claim that the process had ended.
- The model version, settings, tools, generator version, and complete transcript.

## What results tell users

A strong Round 0 result is evidence that the agent found and explained the conflict in this particular set of claims. A strong multi-round result is evidence that, within the tested budget, it kept track of changing constraints, adapted its reasoning, and continued to produce relevant answers under increasing pressure. This makes the test one possible piece of evidence in a broader AGI sandbox evaluation.

It does **not** prove that an agent is AGI, that it will perform well on unrelated tasks, or that any religious belief is true or false. Results depend on the exact model, instructions, tools, generator, evaluator annotations, and budget. Keep the annotations with each transcript because they are part of the test conditions.
