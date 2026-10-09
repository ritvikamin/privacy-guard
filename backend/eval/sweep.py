"""Find good confidence thresholds from data instead of guessing.

The real model is run ONCE over every prompt and its raw answers are cached; then the whole test set is
re-scored under many threshold pairs (this is fast: no model calls after the first pass).

Run from the backend folder (needs torch + transformers):
    python -m eval.sweep
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine as engine_module
from engine import PrivacyEngine
from eval.cases import CASES
from eval.scoring import score_case, summarize

NER_GRID = [0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90]
CODE_GRID = [0.50, 0.70, 0.85, 0.95]


class CachingNER:
    """Remembers the model's raw answer for every text, so re-scoring never calls the model again."""
    def __init__(self, real):
        self.real, self.cache = real, {}

    def __call__(self, chunks):
        missing = [c for c in dict.fromkeys(chunks) if c not in self.cache]
        if missing:
            for chunk, answer in zip(missing, self.real(missing)):
                self.cache[chunk] = answer
        return [self.cache[c] for c in chunks]


def main():
    print("Loading model and running every prompt once...")
    ner = CachingNER(PrivacyEngine().nlp_manager)
    engine = PrivacyEngine(nlp=ner)
    for case in CASES:
        engine.redact(case["text"], {}, {})

    rows = []
    for a in NER_GRID:
        for b in CODE_GRID:
            engine_module.NER_THRESHOLD, engine_module.NER_THRESHOLD_CODE = a, b
            scores = [score_case(c, engine.redact(c["text"], {}, {})) for c in CASES]
            m = summarize(scores, [0.0])
            rows.append({"prose": a, "code": b, "recall": m["recall"], "names_recall": m["recall_names_places_orgs"],
                         "precision": m["precision"], "f1": m["f1"], "over_redaction": m["over_redaction"]})

    rows.sort(key=lambda r: (-r["f1"], -r["recall"]))
    print(f"\n{'prose':>6}{'code':>6}{'recall':>8}{'names':>8}{'prec':>8}{'f1':>7}{'over':>7}")
    for r in rows[:12]:
        print(f"{r['prose']:>6}{r['code']:>6}{r['recall']:>8}{r['names_recall']:>8}{r['precision']:>8}{r['f1']:>7}{r['over_redaction']:>7}")
    cur = next(r for r in rows if r["prose"] == 0.40 and r["code"] == 0.85)
    print(f"\ncurrent setting (0.40 / 0.85): recall {cur['recall']}  precision {cur['precision']}  f1 {cur['f1']}")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "threshold-sweep.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
