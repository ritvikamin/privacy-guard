"""Scoring for the redaction engine: recall (what leaked), precision (what was wrongly tagged),
over-redaction of words that should stay, and latency.

Definitions, so the numbers mean something:
  * A PII string is PROTECTED if none of its pieces survives in the output.
      names/places/orgs : every word of 3+ letters must be gone (so "<PERSON_1> Sharma" is a LEAK)
      everything else   : the whole string and every 6+ character chunk must be gone
  * recall    = protected PII strings / all PII strings
  * precision = correct tags / (correct + wrong tags). A tag is correct if its original value
                matches an expected PII string. Tags on `ignore` strings are not counted.
  * over-redaction = `keep` strings that disappeared / all `keep` strings
"""
import re
import statistics

NAME_TYPES = {"PERSON", "ORG", "LOCATION"}


def _norm(s):
    return re.sub(r"\W+", " ", s.lower()).strip()


def _contains(a, b):
    na, nb = _norm(a), _norm(b)
    return bool(na) and bool(nb) and (na in nb or nb in na)


def leaked_pieces(expected, etype, output):
    """The pieces of `expected` that are still visible in `output` (empty list = protected)."""
    if etype in NAME_TYPES:
        words = [w for w in re.findall(r"\w+", expected) if len(w) >= 3]
        return [w for w in words if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", output)]
    left = [expected] if expected in output else []
    for chunk in re.findall(r"[A-Za-z0-9]{6,}", expected):
        if chunk in output and chunk not in left:
            left.append(chunk)
    return left


def score_case(case, result):
    out = result["redacted"]

    leaks = []
    for s, t in case["pii"]:
        left = leaked_pieces(s, t, out)
        if left:
            leaks.append({"text": s, "type": t, "left": left})

    tags = []
    for tag, value in result["vault"].items():
        base = re.sub(r"_\d+>$", "", tag).lstrip("<")
        status, expected_type = "wrong", None
        for s, t in case["pii"]:
            if _contains(value, s):
                status, expected_type = "correct", t
                break
        else:
            if any(_contains(value, i) for i in case["ignore"]):
                status = "ignored"
        tags.append({"tag": tag, "value": value, "status": status,
                     "type_ok": expected_type == base if status == "correct" else None})

    keep_removed = [k for k in case["keep"] if k not in out]
    return {"id": case["id"], "leaks": leaks, "tags": tags, "keep_removed": keep_removed,
            "n_pii": len(case["pii"]), "n_keep": len(case["keep"]),
            "types": [t for _, t in case["pii"]], "leaked_types": [l["type"] for l in leaks]}


def _pct(num, den):
    return None if den == 0 else round(100.0 * num / den, 1)


def summarize(scores, latencies_ms):
    total = sum(s["n_pii"] for s in scores)
    leaked = sum(len(s["leaks"]) for s in scores)

    by_type = {}
    for s in scores:
        for t in s["types"]:
            by_type.setdefault(t, [0, 0])[0] += 1
        for t in s["leaked_types"]:
            by_type[t][1] += 1
    recall_by_type = {t: _pct(n - l, n) for t, (n, l) in sorted(by_type.items())}

    def group_recall(types):
        n = sum(by_type[t][0] for t in by_type if t in types)
        l = sum(by_type[t][1] for t in by_type if t in types)
        return _pct(n - l, n)

    tags = [t for s in scores for t in s["tags"] if t["status"] != "ignored"]
    correct = sum(1 for t in tags if t["status"] == "correct")
    typed = [t for t in tags if t["status"] == "correct"]
    keep_total = sum(s["n_keep"] for s in scores)
    keep_removed = sum(len(s["keep_removed"]) for s in scores)

    precision = _pct(correct, len(tags))
    recall = _pct(total - leaked, total)
    f1 = None
    if precision is not None and recall is not None and (precision + recall) > 0:
        f1 = round(2 * precision * recall / (precision + recall), 1)

    lat = sorted(latencies_ms)
    return {
        "n_cases": len(scores), "n_pii": total,
        "recall": recall, "precision": precision, "f1": f1,
        "recall_names_places_orgs": group_recall(NAME_TYPES),
        "recall_structured": group_recall(set(by_type) - NAME_TYPES),
        "recall_by_type": recall_by_type,
        "type_accuracy": _pct(sum(1 for t in typed if t["type_ok"]), len(typed)),
        "over_redaction": _pct(keep_removed, keep_total),
        "perfect_cases": _pct(sum(1 for s in scores if not s["leaks"] and not s["keep_removed"]
                                  and all(t["status"] != "wrong" for t in s["tags"])), len(scores)),
        "latency_ms": {"mean": round(statistics.mean(lat), 2), "p50": round(lat[len(lat) // 2], 2),
                       "p95": round(lat[min(len(lat) - 1, int(len(lat) * 0.95))], 2)} if lat else {},
    }
