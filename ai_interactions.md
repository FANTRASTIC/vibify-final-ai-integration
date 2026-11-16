# AI Interactions Log

**Purpose.** This is my record of how I used an AI assistant (Claude, working inside Claude Code) to build Vibify 2.0, what it produced, and what I had to check or fix. The first section shows real traces from the bounded revise loop that I captured by running the project. The later sections cover the agentic workflow I used to build it, the design pattern I ended up with, and the original Vibify 1.0 template.

**How to read it.** Each trace lists the input, the flags the reliability evaluator raised on the first pass, every revision step (the action chosen from the fixed menu, the flag that caused it, which weights changed, the flags afterwards, the top results) and the final list. Flags marked `(info)` fired again but were already handled by a revision. No LLM takes part in that loop: the actions come from a fixed menu keyed by flag. The raw log lines are in [results/agent_traces_sample.jsonl](results/agent_traces_sample.jsonl), a copy of `logs/agent_traces.jsonl` from my runs. It holds four traces; I walk through three below. All runs used the offline mock LLM.

## Agentic Workflow Traces

### Trace 1: converged after a revision (unsupported genre)

- **Input:** `python -m src.main --text "bossa nova for a relaxed evening, acoustic"`
- **Parsed profile:** mood `relaxed`, energy 0.3, likes acoustic, and the genre `bossa nova`, which is not in my catalog.
- **Flags on the first pass:** `NO_GENRE_SUPPORT`, `UNRESOLVED_GENRE`

| Step | Action | Reason flag | Weights changed | Flags after | Top 3 |
|---|---|---|---|---|---|
| 0 | initial | - | none | NO_GENRE_SUPPORT, UNRESOLVED_GENRE | Coffee Shop Stories, Sunday Dub Letter, Glasshouse Fog |
| 1 | drop_genre_rescale | UNRESOLVED_GENRE | none (the genre term is removed and the maximum rescales from 7.0 to 4.5) | UNRESOLVED_GENRE (info) | Coffee Shop Stories, Sunday Dub Letter, Glasshouse Fog |

- **Result:** passed after 1 revision and was not degraded. Catalog support was 0.6744 (moderate).
- **Final top 5:** Coffee Shop Stories, Sunday Dub Letter, Glasshouse Fog, Autumn Letters, Porch Light Moan.
- **What I noticed:** the order did not change. What changed is that the fit percentages are now measured against preferences the catalog can actually satisfy, and the user is told the genre was ignored. I had expected the revision to reshuffle the list, so this was a useful correction to my mental model of what the loop does.

### Trace 2: conflicting preferences (converged, no genre)

- **Input (structured):** `{"moods": ["sad"], "energy": 0.95}`
- **Flags on the first pass:** `CONFLICTING_PREFERENCES`, `FEATURE_MISMATCH`

| Step | Action | Reason flag | Weights changed | Flags after | Top 3 |
|---|---|---|---|---|---|
| 0 | initial | - | none | CONFLICTING_PREFERENCES, FEATURE_MISMATCH | Last Train Blues, Empty Pew Road, Pulse Cathedral |
| 1 | keep_numbers_add_labeled_picks | CONFLICTING_PREFERENCES | none | CONFLICTING_PREFERENCES (info), FEATURE_MISMATCH | Last Train Blues, Empty Pew Road, Pulse Cathedral |
| 2 | boost_energy_weight | FEATURE_MISMATCH | energy 2.0 to 3.0 | LOW_MARGIN, CONFLICTING_PREFERENCES (info) | Pulse Cathedral, Forge of Ashes, Gym Hero |

- **Result:** passed after 2 revisions and was not degraded. A `LOW_MARGIN` warning remains, but it does not block passing.
- **Final list:** Pulse Cathedral (labeled `meets-your-energy`), Forge of Ashes, Gym Hero, Iron Verdict, Storm Runner (labeled `discovery`), Last Train Blues (labeled `meets-your-mood`). My stated numbers were kept, and the labeled picks make the compromise visible instead of hiding it.

### Trace 3: loop exhausted, degraded fallback

- **Input (structured):** `{"genres": ["blues"], "moods": ["sad"], "energy": 0.9, "likes_acoustic": false}`
- **Flags on the first pass:** `CONFLICTING_PREFERENCES`, `FEATURE_MISMATCH`

| Step | Action | Reason flag | Weights changed | Flags after | Top 5 |
|---|---|---|---|---|---|
| 0 | initial | - | none | CONFLICTING_PREFERENCES, FEATURE_MISMATCH | Last Train Blues, Crossroads Static, Storm Runner, Empty Pew Road, Gravel Highway |
| 1 | keep_numbers_add_labeled_picks | CONFLICTING_PREFERENCES | none | CONFLICTING_PREFERENCES (info), FEATURE_MISMATCH | same as step 0 |
| 2 | boost_energy_weight | FEATURE_MISMATCH | energy 2.0 to 3.0 | CONFLICTING_PREFERENCES (info), FEATURE_MISMATCH | Crossroads Static, Last Train Blues, Storm Runner, Gravel Highway, Empty Pew Road |

- **Result:** `FEATURE_MISMATCH` still fired after the 2-revision budget was spent, so the best-evaluated attempt was returned with `degraded = true` and the note "Some quality checks still did not pass after revising, so treat this list as a best effort rather than a confident match." The returned list was the step-1 ordering: Last Train Blues (labeled `meets-your-mood`), Crossroads Static (labeled `meets-your-energy`), Storm Runner, Empty Pew Road, Gravel Highway. Catalog support was moderate.
- **Why it degrades:** my catalog has no high-energy sad blues, so raising the energy weight cannot make a top-3 song match both the genre and the energy.

The fourth trace in the sample file (the text request "sad but high energy", no genre) also ended degraded in the same way. All four traces come from real runs and none was hand-edited.

## Agentic Workflow (SF8)

**What task did I give the agent?**

I gave Claude Code one large, detailed execution prompt and asked it to build Vibify 2.0 end to end in this repository, working autonomously in ten phases (foundation and v1 tests, catalog, scoring v2, knowledge base and retriever, guardrails and evaluator and revise loop, LLM/parser/explainer/pipeline, evaluation harness, Streamlit app and CLI, documentation, final verification). It had to make one git commit per phase, keep the tests passing after each phase, and not push.

**Prompts used:**

- The main prompt, whose key rules I set myself: never fabricate any number, test count or result in the docs (everything must come from a command actually run); keep ranking deterministic, so an LLM may parse text and write explanations but must never score, rank or choose songs; make the whole project reproducible offline with a mock LLM; stay on the standard library plus pytest and streamlit; keep the Vibify 1.0 functions, the two original tests and the default CLI output unchanged; and ask me questions only for a short list of blockers.
- Follow-up prompts after the build: "enhance the UI of this whole thing ... very modern, usable and appealing, include picture or anything if required", then "is there any AI drafts that are recorded here now?", then "please fill up the ai interactions md fully with first person pov".

**What did the agent generate or change?**

- Code: a config module, a validated catalog loader, the v2 scorer, a pure-Python TF-IDF retriever, guardrails, the diversity re-rank, the reliability evaluator, the bounded revise loop, the LLM interface with a deterministic MockLLM, the schema-validated parser, the explainer with its verifier, the pipeline, JSON-line logging, an extended CLI and the Streamlit app (later restyled with generated cover art).
- Data: 30 new fictional songs (ids 20-49) appended to the catalog with ids 1-19 untouched, 16 genre knowledge files plus mood and guide files, 33 evaluation scenarios and draft relevance labels.
- Tests and tooling: 200 tests in total, the evaluation harness, and the committed results.
- Documentation: this README, model card and log, plus `docs/vibify_1_history.md` holding my original Module 3 README and model card.
- Commands it ran and reported: the full pytest suite after each phase, the CLI modes, the harness, a fresh `.venv` with `pip install -r requirements.txt`, and a headless launch of the Streamlit server.

**What did I verify or fix manually?**

I read the results rather than trusting the summaries. Things that needed correcting or that I want on record:

- Three of the agent's first test expectations were wrong. It assumed the discovery slot would fire for a pop profile (the best candidate scored 0.681 against a 0.695 cutoff), that a missing genre would raise `LOW_TOP_SCORE` (it raised `NO_GENRE_SUPPORT`), and that the energy-mismatch action should run before the conflict action. The last one meant a conflict case never reached its labeled picks, so I accepted the fix of reordering the flag priority.
- A scripted test LLM that ran out of replies surfaced as an `INTERNAL_ERROR`. That showed the explainer only caught one kind of backend error, so it now treats any backend failure as a fall-back-to-template event.
- A shell escaping slip turned `\n` into a real line break inside `src/main.py` and caused a syntax error. It was fixed and the v1 output was diffed against the saved original before moving on.
- When I compared the first README draft with the harness output, a few statements were wrong and were corrected: the maximum after dropping the genre was 7.0 to 4.5 (not 6.0 to 4.5), the claim that diversity caps removed the "Gym Hero effect" was not supported (most of the drop came from the bigger catalog), and a stated cause for the lower Diversity@5 had not been verified and was softened.
- The harness showed that v2 did not improve Precision@5 over v1 on the same scenarios (0.74 vs 0.75, against labels that are still a draft), and that turning the evaluator off left the mean unchanged. I kept those results in the docs instead of tuning them away.
- The two prompt-injection scenarios that pass only because the mock parser finds no keywords are weak evidence. The strong evidence is the test where a hostile LLM reply tries to inject weights and an out-of-range energy.
- Still mine to do: review the draft relevance labels, review the hand-set related-genre weights and the generated song attributes, confirm the git remote, and push.

## Design Pattern (SF10)

**Which design pattern did I use?**

The Strategy pattern, applied through a small `LLMClient` protocol, inside a pipeline of narrow stages. A second, simpler pattern is the fixed-menu dispatch in the revise loop, where each evaluator flag maps to one allowed action.

**How did AI help me brainstorm or implement it?**

My first plan made the retrieval layer the required AI feature, and the discussion exposed a problem: a required feature that needs an API key cannot be reproduced by a grader. That pushed the design toward swappable backends. The assistant proposed an `LLMClient` interface with a deterministic `MockLLM` as the default and an optional `AnthropicLLM` that is imported lazily, so the rest of the code never knows which one it is talking to. We also discussed and I rejected a cosine-similarity recommender, because my weighted-closeness scoring already is a similarity measure, and I chose to keep profiles additive with a new `ProfileV2` so the original `UserProfile` and its tests stayed untouched.

**How does the pattern appear in my final code?**

- `src/llm.py`: `LLMClient` (the strategy interface), `MockLLM` (default, deterministic test double), `AnthropicLLM` (optional), and `get_llm()` which picks one from `VIBIFY_LLM` and falls back to the mock if the real backend is unusable.
- `src/parser.py` and `src/explainer.py` take any `LLMClient`, so I can swap the backend without changing them, and tests inject scripted fakes.
- `src/pipeline.py` wires the stages together, and `src/agent.py` holds the flag-to-action menu. The scoring in `src/scoring.py` stays outside the strategy on purpose: no LLM can touch ranking.

## Vibify 1.0 history

The original Vibify 1.0 `ai_interactions.md` was the blank course template (the Agentic Workflow SF8 and Design Pattern SF10 prompts with empty answers), so there was no earlier AI-interaction content to carry over. The sections above are my filled-in versions for Vibify 2.0. The original template is preserved in git history at commit `60b16e0`, and my Module 3 README and model card are in [docs/vibify_1_history.md](docs/vibify_1_history.md).
