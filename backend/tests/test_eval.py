"""Sanity tests for the evaluation harness itself (a wrong scorer would give wrong numbers)."""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval.cases import CASES
from eval.scoring import NAME_TYPES, leaked_pieces, score_case, summarize


class DatasetIsConsistent(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [c["id"] for c in CASES]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_labelled_string_appears_in_its_text(self):
        for c in CASES:
            for s in [p for p, _ in c["pii"]] + c["keep"] + c["ignore"]:
                self.assertIn(s, c["text"], f"{c['id']}: {s!r} not in text")

    def test_leftover_text_cannot_trigger_a_false_leak(self):
        """If we delete every PII string, no checked piece may remain: otherwise a perfect
        redaction would still be scored as a leak."""
        for c in CASES:
            rest = c["text"]
            for s, _ in sorted(c["pii"], key=lambda x: -len(x[0])):
                rest = rest.replace(s, " ")
            for s, t in c["pii"]:
                self.assertEqual(leaked_pieces(s, t, rest), [], f"{c['id']}: {s!r} also appears elsewhere in the text")

    def test_keep_and_pii_do_not_overlap(self):
        for c in CASES:
            for k in c["keep"]:
                for s, _ in c["pii"]:
                    self.assertNotIn(k, s)
                    self.assertNotIn(s, k)


class ScorerBehaves(unittest.TestCase):
    CASE = {"id": "t", "text": "Priya Sharma 9876543210 Python", "keep": ["Python"], "ignore": ["Paris"],
            "pii": [("Priya Sharma", "PERSON"), ("9876543210", "PHONE_NUMBER")]}

    def test_half_redacted_name_counts_as_a_leak(self):
        r = {"redacted": "<PERSON_1> Sharma <PHONE_NUMBER_1> Python",
             "vault": {"<PERSON_1>": "Priya", "<PHONE_NUMBER_1>": "9876543210"}}
        s = score_case(self.CASE, r)
        self.assertEqual([l["text"] for l in s["leaks"]], ["Priya Sharma"])
        self.assertTrue(all(t["status"] == "correct" for t in s["tags"]))

    def test_perfect_redaction(self):
        r = {"redacted": "<PERSON_1> <PHONE_NUMBER_1> Python",
             "vault": {"<PERSON_1>": "Priya Sharma", "<PHONE_NUMBER_1>": "9876543210"}}
        s = score_case(self.CASE, r)
        self.assertEqual((s["leaks"], s["keep_removed"]), ([], []))
        m = summarize([s], [1.0])
        self.assertEqual((m["recall"], m["precision"], m["over_redaction"]), (100.0, 100.0, 0.0))

    def test_wrong_tag_and_over_redaction(self):
        r = {"redacted": "<PERSON_1> <PHONE_NUMBER_1> <ORG_1>",
             "vault": {"<PERSON_1>": "Priya Sharma", "<PHONE_NUMBER_1>": "9876543210", "<ORG_1>": "Python"}}
        s = score_case(self.CASE, r)
        self.assertEqual(s["keep_removed"], ["Python"])
        self.assertEqual([t["status"] for t in s["tags"]], ["correct", "correct", "wrong"])
        self.assertAlmostEqual(summarize([s], [1.0])["precision"], 66.7, places=1)

    def test_ignored_strings_do_not_hurt_precision(self):
        case = {"id": "i", "text": "Paris", "pii": [], "keep": [], "ignore": ["Paris"]}
        s = score_case(case, {"redacted": "<LOCATION_1>", "vault": {"<LOCATION_1>": "Paris"}})
        self.assertEqual(s["tags"][0]["status"], "ignored")
        self.assertIsNone(summarize([s], [1.0])["precision"])

    def test_structured_partial_redaction_is_caught(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertTrue(leaked_pieces(jwt, "SECRET_TOKEN", "Bearer <SECRET_TOKEN_1>.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"))


if __name__ == "__main__":
    unittest.main()
