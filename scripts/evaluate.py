"""Evaluation harness for Vibify 2.0.

    python scripts/evaluate.py [--runs N] [--json-only] [--scenarios F] [--labels F] [--out-dir D]

Runs every scenario through the v2 pipeline (mock LLM unless VIBIFY_LLM says otherwise), runs the
Vibify 1.0 baseline where its inputs allow, computes metrics, writes results/eval_results.json and
results/eval_summary.md, and exits 0 only if every scenario assertion passed.

Precision@5 uses data/relevance_labels.json, which is DRAFT (labeled by the AI assistant from plain
descriptions) until the author reviews it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.catalog import load_catalog  # noqa: E402
from src.config import Config  # noqa: E402
from src.logging_setup import close_loggers  # noqa: E402
from src.pipeline import VibifyPipeline  # noqa: E402
from src.recommender import load_songs, recommend_songs  # noqa: E402

V1_KEYS = {"genres", "moods", "energy", "likes_acoustic"}


# ----------------------------------------------------------------------------- helpers
def v1_prefs(inp) -> Optional[Dict]:
    """Translate a structured scenario into a v1 prefs dict, or None if v1 cannot express it."""
    if not isinstance(inp, dict) or not set(inp) <= V1_KEYS:
        return None
    if len(inp.get("genres", [])) > 1 or len(inp.get("moods", [])) > 1:
        return None
    prefs: Dict = {}
    if inp.get("genres"):
        prefs["genre"] = inp["genres"][0]
    if inp.get("moods"):
        prefs["mood"] = inp["moods"][0]
    if "energy" in inp:
        prefs["energy"] = inp["energy"]
    if "likes_acoustic" in inp:
        prefs["likes_acoustic"] = inp["likes_acoustic"]
    return prefs


def stable_view(result) -> str:
    d = result.to_dict()
    d.pop("request_id", None)
    d.pop("latency_ms", None)
    return json.dumps(d, sort_keys=True, default=str)


def check_expect(expect: Dict, result, cfg_before, cfg) -> List[str]:
    problems = []
    if "ok" in expect and result.ok != expect["ok"]:
        problems.append(f"expected ok={expect['ok']} got ok={result.ok} ({result.error_code})")
    if "error_code" in expect and result.error_code != expect["error_code"]:
        problems.append(f"expected error {expect['error_code']} got {result.error_code}")
    for code in expect.get("flags_include", []):
        if code not in result.flag_codes():
            problems.append(f"missing flag {code}")
    for code in expect.get("flags_exclude", []):
        if code in result.flag_codes():
            problems.append(f"unexpected flag {code}")
    if expect.get("config_unchanged"):
        if (dict(cfg.weights_v2), cfg.low_top_score, cfg.max_revisions) != cfg_before or \
                "weights_override" in result.profile:
            problems.append("scoring configuration changed")
    if result.ok and not result.items:
        problems.append("ok result with no items")
    return problems


def top_ids(items, n=5) -> List[int]:
    return [i["song"]["id"] if isinstance(i, dict) else i[0]["id"] for i in items[:n]]


def precision_at_5(top: List[int], relevant: List[int]) -> float:
    return len(set(top[:5]) & set(relevant)) / 5.0


def diversity_at_5(tops: List[List[Dict]]) -> float:
    vals = []
    for songs in tops:
        if songs:
            vals.append((len({s["artist"] for s in songs}) / 5 + len({s["genre"] for s in songs}) / 5) / 2)
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def summarize_system(tops: Dict[str, List[Dict]], labels: Dict[str, List[int]], catalog: List[Dict]) -> Dict:
    ps = [precision_at_5([s["id"] for s in songs], labels[sid]) for sid, songs in tops.items() if sid in labels]
    genres = {s["genre"] for songs in tops.values() for s in songs}
    counts: Counter = Counter(s["id"] for songs in tops.values() for s in songs)
    titles = {s["id"]: s["title"] for s in catalog}
    n = len(tops)
    top3 = [{"title": titles[i], "scenarios": c, "share": round(c / n, 4)} for i, c in counts.most_common(3)] if n else []
    return {"n_scenarios": n, "n_labeled": len(ps),
            "precision_at_5": round(sum(ps) / len(ps), 4) if ps else None,
            "diversity_at_5": diversity_at_5(list(tops.values())),
            "genre_coverage": round(len(genres) / len({s["genre"] for s in catalog}), 4),
            "genres_covered": len(genres), "genres_in_catalog": len({s["genre"] for s in catalog}),
            "dominance_top3": top3, "max_share": top3[0]["share"] if top3 else 0.0}


# ----------------------------------------------------------------------------- main run
def run_harness(scenarios: List[Dict], labels: Dict[str, List[int]], runs: int, catalog_path: str,
                log_dir: str) -> Dict:
    catalog = load_catalog(catalog_path)
    cfg = Config(log_dir=log_dir)
    pipe = VibifyPipeline(songs_path=catalog_path, config=cfg)
    pipe_off = VibifyPipeline(songs_path=catalog_path, config=Config(log_dir=log_dir, evaluator_enabled=False))
    cfg_before = (dict(cfg.weights_v2), cfg.low_top_score, cfg.max_revisions)
    v1_songs = load_songs(catalog_path)

    rows: List[Dict] = []
    v2_tops: Dict[str, List[Dict]] = {}
    off_tops: Dict[str, List[Dict]] = {}
    v1_tops: Dict[str, List[Dict]] = {}
    v1_fail = {"eligible": 0, "unexpected_failures": 0, "unexpected_successes": 0}
    v2_fail = {"unexpected_failures": 0, "unexpected_successes": 0}
    flag_counts: Counter = Counter()
    sources: Counter = Counter()
    supports: List[float] = []
    degraded = 0
    consistent = 0

    for sc in scenarios:
        run = (lambda p: p.recommend_text(sc["input"])) if sc["input_type"] == "text" else \
              (lambda p: p.recommend(sc["input"]))
        results = [run(pipe) for _ in range(runs)]
        res = results[0]
        same = len({stable_view(r) for r in results}) == 1
        consistent += same
        problems = check_expect(sc["expect"], res, cfg_before, cfg)
        expect_ok = sc["expect"].get("ok")
        if expect_ok is True and not res.ok:
            v2_fail["unexpected_failures"] += 1
        if expect_ok is False and res.ok:
            v2_fail["unexpected_successes"] += 1
        row = {"id": sc["id"], "category": sc["category"], "input_type": sc["input_type"],
               "description": sc["description"], "ok": res.ok, "error_code": res.error_code,
               "flags": res.flag_codes(), "degraded": res.degraded,
               "top1": res.items[0].song["title"] if res.items else None,
               "top5_ids": [i.song["id"] for i in res.items[:5]], "consistent": same,
               "passed": not problems, "problems": problems}
        if res.ok:
            v2_tops[sc["id"]] = [i.song for i in res.items[:5]]
            flag_counts.update(set(res.flag_codes()))
            degraded += res.degraded
            if res.catalog_support.get("value") is not None:
                supports.append(res.catalog_support["value"])
            sources.update(i.explanation_source for i in res.items)
            if sc["id"] in labels:
                row["precision_at_5"] = precision_at_5(row["top5_ids"], labels[sc["id"]])
            off = run(pipe_off)
            if off.ok:
                off_tops[sc["id"]] = [i.song for i in off.items[:5]]
        # v1 baseline
        if sc["input_type"] == "structured":
            prefs = v1_prefs(sc["input"])
            if prefs is not None:
                v1_fail["eligible"] += 1
                top = [s for s, _, _ in recommend_songs(prefs, v1_songs, 5)]
                if expect_ok is False:
                    v1_fail["unexpected_successes"] += 1   # v1 has no validation: it always "succeeds"
                elif expect_ok is True:
                    v1_tops[sc["id"]] = top
                    row["v1_top5_ids"] = [s["id"] for s in top]
                    if sc["id"] in labels:
                        row["v1_precision_at_5"] = precision_at_5(row["v1_top5_ids"], labels[sc["id"]])
        rows.append(row)

    eligible_ids = set(v1_tops)
    metrics = {
        "v1_baseline": summarize_system(v1_tops, labels, catalog),
        "v2_on_v1_eligible_subset": summarize_system({k: v for k, v in v2_tops.items() if k in eligible_ids},
                                                     labels, catalog),
        "v2_all_ok_scenarios": summarize_system(v2_tops, labels, catalog),
        "v2_evaluator_disabled_all_ok_scenarios": summarize_system(off_tops, labels, catalog),
    }
    guard = [r for r in rows if r["category"] in ("invalid", "injection")]
    out = {
        "meta": {"n_scenarios": len(scenarios), "runs_per_scenario": runs, "catalog_size": len(catalog),
                 "llm_backend": pipe.llm_name, "label_status": json.load(open(ROOT / "data" / "relevance_labels.json",
                                                                              encoding="utf-8"))["status"]
                 if (ROOT / "data" / "relevance_labels.json").exists() else "unknown"},
        "scenarios": rows,
        "metrics": metrics,
        "failure_rate": {"v1": {**v1_fail, "note": "v1 is run only on structured scenarios whose fields it supports"},
                         "v2": v2_fail},
        "consistency": {"identical_across_runs": consistent, "of": len(scenarios), "runs": runs,
                        "note": "In mock mode this is deterministic by construction; it only becomes "
                                "informative with a real LLM backend."},
        "evaluator_stats": {"flag_counts_by_code": dict(sorted(flag_counts.items())), "degraded": degraded,
                            "avg_catalog_support": round(sum(supports) / len(supports), 4) if supports else None,
                            "explanation_sources": dict(sources)},
        "guardrails": {"passed": sum(r["passed"] for r in guard), "of": len(guard),
                       "scenarios": [{"id": r["id"], "passed": r["passed"]} for r in guard]},
        "all_passed": all(r["passed"] for r in rows),
    }
    pipe.llm  # noqa: B018
    close_loggers()
    return out


# ----------------------------------------------------------------------------- output
def fmt(v) -> str:
    return "n/a" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def render_table(out: Dict) -> str:
    lines = ["| ID | Category | Input | Result | Flags | Top-1 | P@5 | Status |", "|---|---|---|---|---|---|---|---|"]
    for r in out["scenarios"]:
        res = "ok" if r["ok"] else f"error {r['error_code']}"
        lines.append(f"| {r['id']} | {r['category']} | {r['input_type']} | {res} | "
                     f"{', '.join(r['flags']) or '-'} | {r['top1'] or '-'} | {fmt(r.get('precision_at_5'))} | "
                     f"{'PASS' if r['passed'] else 'FAIL: ' + '; '.join(r['problems'])} |")
    return "\n".join(lines)


def render_summary(out: Dict) -> str:
    m, meta = out["metrics"], out["meta"]
    v1, v2s, v2a, off = (m["v1_baseline"], m["v2_on_v1_eligible_subset"], m["v2_all_ok_scenarios"],
                         m["v2_evaluator_disabled_all_ok_scenarios"])
    L = ["# Vibify evaluation summary", "",
         f"Scenarios: {meta['n_scenarios']} | runs per scenario: {meta['runs_per_scenario']} | catalog: "
         f"{meta['catalog_size']} songs | LLM backend: {meta['llm_backend']}", "",
         f"Precision@5 label status: **{meta['label_status']}**", "", "## Per-scenario results", "",
         render_table(out), "", "## Metrics: v1 vs v2", "",
         "| Metric | v1 baseline | v2 (same scenarios as v1) | v2 (all ok scenarios) | v2 evaluator disabled |",
         "|---|---|---|---|---|",
         f"| Scenarios | {v1['n_scenarios']} | {v2s['n_scenarios']} | {v2a['n_scenarios']} | {off['n_scenarios']} |",
         f"| Precision@5 (DRAFT labels) | {fmt(v1['precision_at_5'])} | {fmt(v2s['precision_at_5'])} | "
         f"{fmt(v2a['precision_at_5'])} | {fmt(off['precision_at_5'])} |",
         f"| Diversity@5 | {fmt(v1['diversity_at_5'])} | {fmt(v2s['diversity_at_5'])} | {fmt(v2a['diversity_at_5'])} | "
         f"{fmt(off['diversity_at_5'])} |",
         f"| Genre coverage | {fmt(v1['genre_coverage'])} ({v1['genres_covered']}/{v1['genres_in_catalog']}) | "
         f"{fmt(v2s['genre_coverage'])} ({v2s['genres_covered']}/{v2s['genres_in_catalog']}) | "
         f"{fmt(v2a['genre_coverage'])} ({v2a['genres_covered']}/{v2a['genres_in_catalog']}) | "
         f"{fmt(off['genre_coverage'])} |",
         f"| Max dominance share | {fmt(v1['max_share'])} | {fmt(v2s['max_share'])} | {fmt(v2a['max_share'])} | "
         f"{fmt(off['max_share'])} |", "", "## Dominance (most frequent songs in top 5)", "",
         "| System | Song | Scenarios | Share |", "|---|---|---|---|"]
    for name, s in (("v1", v1), ("v2 (v1 subset)", v2s), ("v2 (all)", v2a)):
        for d in s["dominance_top3"]:
            L.append(f"| {name} | {d['title']} | {d['scenarios']} | {d['share']:.2f} |")
    fr = out["failure_rate"]
    L += ["", "## Failure rate", "", "| System | Unexpected failures | Unexpected successes | Scenarios considered |",
          "|---|---|---|---|",
          f"| v1 | {fr['v1']['unexpected_failures']} | {fr['v1']['unexpected_successes']} | {fr['v1']['eligible']} "
          "(structured, v1-expressible) |",
          f"| v2 | {fr['v2']['unexpected_failures']} | {fr['v2']['unexpected_successes']} | {meta['n_scenarios']} |",
          "", "## Consistency", "",
          f"{out['consistency']['identical_across_runs']} of {out['consistency']['of']} scenarios gave identical output "
          f"across {out['consistency']['runs']} runs. {out['consistency']['note']}", "", "## Evaluator statistics", "",
          "| Flag code | Scenarios raising it |", "|---|---|"]
    for code, n in out["evaluator_stats"]["flag_counts_by_code"].items():
        L.append(f"| {code} | {n} |")
    es = out["evaluator_stats"]
    L += ["", f"Degraded results: {es['degraded']} | average catalog_support: {fmt(es['avg_catalog_support'])} "
              "(heuristic, not a probability)", "",
          "Explanation sources (mock mode: 'llm' means the deterministic MockLLM): "
          + ", ".join(f"{k}={v}" for k, v in sorted(es["explanation_sources"].items())), "",
          "## Guardrail scenarios (invalid and injection)", "", "| Scenario | Result |", "|---|---|"]
    for g in out["guardrails"]["scenarios"]:
        L.append(f"| {g['id']} | {'PASS' if g['passed'] else 'FAIL'} |")
    L += ["", f"Guardrail scenarios passed: {out['guardrails']['passed']} of {out['guardrails']['of']}",
          f"All scenario assertions passed: {out['all_passed']}", ""]
    return "\n".join(L)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Vibify evaluation harness")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--scenarios", default=str(ROOT / "data" / "eval_profiles.json"))
    ap.add_argument("--labels", default=str(ROOT / "data" / "relevance_labels.json"))
    ap.add_argument("--catalog", default=str(ROOT / "data" / "songs.csv"))
    ap.add_argument("--out-dir", default=str(ROOT / "results"))
    args = ap.parse_args(argv)

    scenarios = json.load(open(args.scenarios, encoding="utf-8"))
    labels = json.load(open(args.labels, encoding="utf-8")).get("labels", {})
    with tempfile.TemporaryDirectory() as tmp:
        out = run_harness(scenarios, labels, max(1, args.runs), args.catalog, tmp)
    os.makedirs(args.out_dir, exist_ok=True)
    with open(Path(args.out_dir) / "eval_results.json", "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1, sort_keys=True)
        f.write("\n")
    with open(Path(args.out_dir) / "eval_summary.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(render_summary(out))
    if args.json_only:
        print(json.dumps(out, indent=1, sort_keys=True))
    else:
        print(render_table(out))
        print()
        print(render_summary(out).split("## Metrics: v1 vs v2", 1)[1].join(["## Metrics: v1 vs v2", ""]))
    return 0 if out["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
