"""Score the redaction engine on the labelled prompts in eval/cases.py.

Run from the backend folder:
    python -m eval.run_eval --engine regex                  # regex layer only (no model needed)
    python -m eval.run_eval --engine bert --label bert-large   # the real model (needs torch + transformers)
    python -m eval.run_eval --compare eval/results/a.json eval/results/b.json
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.cases import CASES
from eval.scoring import score_case, summarize

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def rss_mb():
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 1e6)
    except Exception:
        return None


def build_engine(kind):
    from engine import PrivacyEngine
    if kind == "regex":
        return PrivacyEngine(nlp=lambda chunks: [[] for _ in chunks])      # no name detection at all
    if kind == "bert":
        return PrivacyEngine()                                              # real BERT through torch
    raise SystemExit(f"unknown engine: {kind}")


def run(kind, label, verbose):
    t0 = time.perf_counter()
    engine = build_engine(kind)
    load_s = round(time.perf_counter() - t0, 2)
    engine.redact("warm up Priya Sharma", {}, {})            # first call is slow; do not time it

    scores, latencies = [], []
    for case in CASES:
        t = time.perf_counter()
        result = engine.redact(case["text"], {}, {})
        latencies.append((time.perf_counter() - t) * 1000)
        scores.append(score_case(case, result))
        if verbose:
            print(f"\n[{case['id']}] {case['text']!r}\n   -> {result['redacted']!r}")

    metrics = summarize(scores, latencies)
    failures = [s for s in scores if s["leaks"] or s["keep_removed"] or any(t["status"] == "wrong" for t in s["tags"])]
    report = {"label": label, "engine": kind, "load_seconds": load_s, "rss_mb_after_run": rss_mb(),
              "metrics": metrics, "failures": failures}
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{label}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    print_report(report)
    print(f"\nSaved: {path}")


def print_report(r):
    m = r["metrics"]
    print(f"\n=== {r['label']}  (engine: {r['engine']}) ===")
    print(f"cases: {m['n_cases']}   PII strings: {m['n_pii']}")
    print(f"recall    {m['recall']}%   (names/places/orgs {m['recall_names_places_orgs']}%, structured IDs {m['recall_structured']}%)")
    print(f"precision {m['precision']}%   f1 {m['f1']}   type accuracy {m['type_accuracy']}%")
    print(f"over-redaction of words that should stay: {m['over_redaction']}%")
    print(f"perfect cases: {m['perfect_cases']}%")
    print("recall by type:", ", ".join(f"{k} {v}%" for k, v in m["recall_by_type"].items()))
    print(f"latency per prompt: mean {m['latency_ms'].get('mean')} ms, p50 {m['latency_ms'].get('p50')} ms, p95 {m['latency_ms'].get('p95')} ms")
    print(f"model load: {r['load_seconds']} s   memory after run: {r['rss_mb_after_run']} MB (needs psutil)")
    print("\n--- what went wrong ---")
    for f in r["failures"]:
        for l in f["leaks"]:
            print(f"  LEAK   [{f['id']}] {l['type']} {l['text']!r} -> still visible: {l['left']}")
        for t in f["tags"]:
            if t["status"] == "wrong":
                print(f"  WRONG  [{f['id']}] {t['tag']} replaced {t['value']!r} (not PII)")
        for k in f["keep_removed"]:
            print(f"  OVER   [{f['id']}] removed {k!r}, which should stay")


def compare(a_path, b_path):
    a, b = (json.load(open(p, encoding="utf-8")) for p in (a_path, b_path))
    rows = [("recall %", "recall"), ("  names/places/orgs %", "recall_names_places_orgs"), ("  structured IDs %", "recall_structured"),
            ("precision %", "precision"), ("f1", "f1"), ("over-redaction %", "over_redaction")]
    print(f"\n{'metric':28}{a['label']:>18}{b['label']:>18}")
    for name, key in rows:
        print(f"{name:28}{str(a['metrics'][key]):>18}{str(b['metrics'][key]):>18}")
    for k in ("mean", "p95"):
        print(f"{'latency ' + k + ' (ms)':28}{a['metrics']['latency_ms'][k]:>18}{b['metrics']['latency_ms'][k]:>18}")
    for name, key in (("model load (s)", "load_seconds"), ("memory (MB)", "rss_mb_after_run")):
        print(f"{name:28}{str(a[key]):>18}{str(b[key]):>18}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", choices=["regex", "bert"])
    ap.add_argument("--label")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"))
    args = ap.parse_args()
    if args.compare:
        compare(*args.compare)
    elif args.engine:
        run(args.engine, args.label or args.engine, args.verbose)
    else:
        ap.print_help()
