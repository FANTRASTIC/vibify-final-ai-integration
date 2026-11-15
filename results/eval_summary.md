# Vibify evaluation summary

Scenarios: 33 | runs per scenario: 3 | catalog: 49 songs | LLM backend: mock

Precision@5 label status: **DRAFT - labeled by the AI assistant from scenario descriptions; the author must review and edit before these numbers are cited as final**

## Per-scenario results

| ID | Category | Input | Result | Flags | Top-1 | P@5 | Status |
|---|---|---|---|---|---|---|---|
| S01 | normal | structured | ok | - | Sunrise City | 1.00 | PASS |
| S02 | normal | structured | ok | - | Midnight Coding | 0.60 | PASS |
| S03 | normal | structured | ok | - | Storm Runner | 0.80 | PASS |
| S04 | adversarial | structured | ok | CONFLICTING_PREFERENCES, FEATURE_MISMATCH | Last Train Blues | 0.80 | PASS |
| S05 | adversarial | structured | ok | - | Sunrise City | 1.00 | PASS |
| S06 | adversarial | structured | ok | - | Quiet Neon Hours | 0.60 | PASS |
| S07 | normal | structured | ok | - | Coffee Shop Stories | 0.60 | PASS |
| S08 | normal | structured | ok | - | Pulse Cathedral | 0.80 | PASS |
| S09 | normal | structured | ok | - | Moonlit Sonata Revisited | 0.80 | PASS |
| S10 | normal | structured | ok | - | Dusty Porch Light | 0.80 | PASS |
| S11 | normal | structured | ok | - | Concrete Crown | 1.00 | PASS |
| S12 | normal | structured | ok | - | Autumn Letters | 0.80 | PASS |
| S13 | normal | structured | ok | TOO_FEW_RESULTS | Island Hammock | 0.40 | PASS |
| S14 | normal | structured | ok | - | Iron Verdict | 0.60 | PASS |
| S15 | normal | structured | ok | - | Silk Telephone | 1.00 | PASS |
| S16 | normal | structured | ok | - | Night Drive Loop | 0.80 | PASS |
| S17 | adversarial | structured | ok | UNRESOLVED_GENRE | Coffee Shop Stories | 0.40 | PASS |
| S18 | adversarial | structured | ok | LOW_MARGIN, CONFLICTING_PREFERENCES | Pulse Cathedral | 0.60 | PASS |
| S19 | normal | structured | ok | - | Crossroads Static | 0.80 | PASS |
| S20 | normal | structured | ok | - | Sunrise City | 1.00 | PASS |
| T01 | normal | text | ok | - | Focus Flow | 0.80 | PASS |
| T02 | normal | text | ok | - | Basement Frequency | 0.80 | PASS |
| T03 | normal | text | ok | - | Autumn Letters | 0.80 | PASS |
| T04 | normal | text | ok | LOW_MARGIN | Voltage Garden | 0.80 | PASS |
| I01 | invalid | structured | error EMPTY_PROFILE | - | - | n/a | PASS |
| I02 | invalid | text | error EMPTY_TEXT | - | - | n/a | PASS |
| I03 | invalid | structured | error ENERGY_OUT_OF_RANGE | - | - | n/a | PASS |
| I04 | invalid | structured | error TEMPO_OUT_OF_RANGE | - | - | n/a | PASS |
| I05 | invalid | text | error TEXT_TOO_LONG | - | - | n/a | PASS |
| I06 | invalid | text | error EMPTY_PROFILE | - | - | n/a | PASS |
| J01 | injection | text | error EMPTY_PROFILE | - | - | n/a | PASS |
| J02 | injection | text | error EMPTY_PROFILE | - | - | n/a | PASS |
| J03 | injection | text | ok | - | Storm Runner | 0.80 | PASS |

## Metrics: v1 vs v2

| Metric | v1 baseline | v2 (same scenarios as v1) | v2 (all ok scenarios) | v2 evaluator disabled |
|---|---|---|---|---|
| Scenarios | 17 | 17 | 25 | 25 |
| Precision@5 (DRAFT labels) | 0.75 | 0.74 | 0.77 | 0.77 |
| Diversity@5 | 0.79 | 0.81 | 0.83 | 0.86 |
| Genre coverage | 1.00 (16/16) | 1.00 (16/16) | 1.00 (16/16) | 1.00 |
| Max dominance share | 0.24 | 0.24 | 0.28 | 0.28 |

## Dominance (most frequent songs in top 5)

| System | Song | Scenarios | Share |
|---|---|---|---|
| v1 | Glass Confetti | 4 | 0.24 |
| v1 | Sunrise City | 3 | 0.18 |
| v1 | Gym Hero | 3 | 0.18 |
| v2 (v1 subset) | Storm Runner | 4 | 0.24 |
| v2 (v1 subset) | Gravel Highway | 4 | 0.24 |
| v2 (v1 subset) | Empty Pew Road | 4 | 0.24 |
| v2 (all) | Storm Runner | 7 | 0.28 |
| v2 (all) | Gravel Highway | 6 | 0.24 |
| v2 (all) | Last Train Blues | 6 | 0.24 |

## Failure rate

| System | Unexpected failures | Unexpected successes | Scenarios considered |
|---|---|---|---|
| v1 | 0 | 2 | 19 (structured, v1-expressible) |
| v2 | 0 | 0 | 33 |

## Consistency

33 of 33 scenarios gave identical output across 3 runs. In mock mode this is deterministic by construction; it only becomes informative with a real LLM backend.

## Evaluator statistics

| Flag code | Scenarios raising it |
|---|---|
| CONFLICTING_PREFERENCES | 2 |
| FEATURE_MISMATCH | 1 |
| LOW_MARGIN | 2 |
| TOO_FEW_RESULTS | 1 |
| UNRESOLVED_GENRE | 1 |

Degraded results: 1 | average catalog_support: 0.83 (heuristic, not a probability)

Explanation sources (mock mode: 'llm' means the deterministic MockLLM): llm=123

## Guardrail scenarios (invalid and injection)

| Scenario | Result |
|---|---|
| I01 | PASS |
| I02 | PASS |
| I03 | PASS |
| I04 | PASS |
| I05 | PASS |
| I06 | PASS |
| J01 | PASS |
| J02 | PASS |
| J03 | PASS |

Guardrail scenarios passed: 9 of 9
All scenario assertions passed: True
