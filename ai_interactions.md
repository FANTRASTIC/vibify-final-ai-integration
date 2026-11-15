# AI Interactions Log

**Purpose.** This file documents how AI was used in Vibify and gives evidence of the agentic workflow (stretch feature). The first section shows real traces from the bounded revise loop in `src/agent.py`, captured from actual runs of this repository. The last section preserves the original, unmodified Vibify 1.0 template content.

**How to read it.** Each trace lists the input, the flags the reliability evaluator raised on the first pass, every revision step (the action chosen from the fixed menu, the flag that caused it, which weights changed, the flags afterwards, the top results) and the final list. Flags marked `(info)` were raised again but already handled by a revision. No LLM takes part in this loop: the actions come from a fixed menu keyed by flag. The raw log lines are in [results/agent_traces_sample.jsonl](results/agent_traces_sample.jsonl) (a copy of `logs/agent_traces.jsonl` from these runs); the file contains four traces and three are shown below. The runs used the offline mock LLM.

## Agentic Workflow Traces

### Trace 1: converged after a revision (unsupported genre)

- **Input:** `python -m src.main --text "bossa nova for a relaxed evening, acoustic"`
- **Parsed profile:** moods `relaxed`, energy 0.3, likes acoustic; genre `bossa nova` (not in the catalog)
- **Flags on the first pass:** `NO_GENRE_SUPPORT`, `UNRESOLVED_GENRE`

| Step | Action | Reason flag | Weights changed | Flags after | Top 3 |
|---|---|---|---|---|---|
| 0 | initial | - | none | NO_GENRE_SUPPORT, UNRESOLVED_GENRE | Coffee Shop Stories, Sunday Dub Letter, Glasshouse Fog |
| 1 | drop_genre_rescale | UNRESOLVED_GENRE | none (the genre term is removed and the maximum rescales, 7.0 to 4.5) | UNRESOLVED_GENRE (info) | Coffee Shop Stories, Sunday Dub Letter, Glasshouse Fog |

- **Result:** passed after 1 revision, not degraded; catalog support 0.6744 (moderate).
- **Final top 5:** Coffee Shop Stories, Sunday Dub Letter, Glasshouse Fog, Autumn Letters, Porch Light Moan.
- **Note:** the order did not change; what changed is that the fractions are now computed against the preferences that could be satisfied, and the user is told the genre was ignored.

### Trace 2: conflicting preferences (converged, no genre)

- **Input (structured):** `{"moods": ["sad"], "energy": 0.95}`
- **Flags on the first pass:** `CONFLICTING_PREFERENCES`, `FEATURE_MISMATCH`

| Step | Action | Reason flag | Weights changed | Flags after | Top 3 |
|---|---|---|---|---|---|
| 0 | initial | - | none | CONFLICTING_PREFERENCES, FEATURE_MISMATCH | Last Train Blues, Empty Pew Road, Pulse Cathedral |
| 1 | keep_numbers_add_labeled_picks | CONFLICTING_PREFERENCES | none | CONFLICTING_PREFERENCES (info), FEATURE_MISMATCH | Last Train Blues, Empty Pew Road, Pulse Cathedral |
| 2 | boost_energy_weight | FEATURE_MISMATCH | energy 2.0 to 3.0 | LOW_MARGIN, CONFLICTING_PREFERENCES (info) | Pulse Cathedral, Forge of Ashes, Gym Hero |

- **Result:** passed after 2 revisions, not degraded (a `LOW_MARGIN` warning remains, which does not block passing).
- **Final list:** Pulse Cathedral (labeled `meets-your-energy`), Forge of Ashes, Gym Hero, Iron Verdict, Storm Runner (labeled `discovery`), Last Train Blues (labeled `meets-your-mood`). The user's stated numbers were kept; the labeled picks make the compromise visible.

### Trace 3: loop exhausted, degraded fallback

- **Input (structured):** `{"genres": ["blues"], "moods": ["sad"], "energy": 0.9, "likes_acoustic": false}`
- **Flags on the first pass:** `CONFLICTING_PREFERENCES`, `FEATURE_MISMATCH`

| Step | Action | Reason flag | Weights changed | Flags after | Top 5 |
|---|---|---|---|---|---|
| 0 | initial | - | none | CONFLICTING_PREFERENCES, FEATURE_MISMATCH | Last Train Blues, Crossroads Static, Storm Runner, Empty Pew Road, Gravel Highway |
| 1 | keep_numbers_add_labeled_picks | CONFLICTING_PREFERENCES | none | CONFLICTING_PREFERENCES (info), FEATURE_MISMATCH | same as step 0 |
| 2 | boost_energy_weight | FEATURE_MISMATCH | energy 2.0 to 3.0 | CONFLICTING_PREFERENCES (info), FEATURE_MISMATCH | Crossroads Static, Last Train Blues, Storm Runner, Gravel Highway, Empty Pew Road |

- **Result:** `FEATURE_MISMATCH` still fired after the revision budget (2) was spent, so the best-evaluated attempt was returned with `degraded = true` and the note "Some quality checks still did not pass after revising, so treat this list as a best effort rather than a confident match." The returned list was the step-1 ordering: Last Train Blues, Crossroads Static, Storm Runner, Empty Pew Road, Gravel Highway, with Last Train Blues labeled `meets-your-mood` and Crossroads Static labeled `meets-your-energy`. Catalog support was moderate.
- **Why it degrades:** the catalog contains no high-energy sad blues, so raising the weight on energy cannot make a top-3 song match both the genre and the energy.

A fourth trace in the sample file (the text request "sad but high energy", no genre) also ended degraded in the same way. All four cases were produced by real runs; none was hand-edited.

## AI assistant collaboration notes

An AI assistant (Claude, in Claude Code) planned and implemented Vibify 2.0. The decisions it proposed and the ones that were changed or rejected are recorded in the AI Collaboration section of [model_card.md](model_card.md), together with what the assistant got wrong during this build. The human author is expected to edit those notes so they match their own experience.

---

## Vibify 1.0 history

The content below is the original `ai_interactions.md` template from Vibify 1.0, preserved verbatim.

# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agentic Workflow (SF8)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**What task did you give the agent?**

<!-- Describe the goal you asked the agent to accomplish -->

**Prompts used:**

<!-- Paste the key prompts you gave the agent -->

**What did the agent generate or change?**

<!-- List the files edited, code generated, or commands run -->

**What did you verify or fix manually?**

<!-- Describe anything the agent got wrong or that required human review -->

---

## Design Pattern (SF10)

> Document how AI helped you choose or implement a design pattern.

**Which design pattern did you use?**

<!-- e.g., Strategy, Factory, Observer, etc. -->

**How did AI help you brainstorm or implement it?**

<!-- Describe the conversation or suggestions that led to your decision -->

**How does the pattern appear in your final code?**

<!-- Point to the relevant class or method -->
