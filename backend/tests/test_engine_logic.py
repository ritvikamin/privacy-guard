"""Logic tests for engine.py using a FAKE NER model (no BERT download needed).

They check OUR rules: label mapping, code-line thresholds, chunking, tag consistency.
Accuracy of the real BERT model is measured separately (precision/recall test set).

Run from the backend folder:  python -m unittest discover -s tests -v
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from engine import PrivacyEngine, MAX_CHUNK_CHARS


class FakeNER:
    """Finds the words in `table` and reports them like the real pipeline would."""
    def __init__(self, table):
        self.table = table            # {"Ritvik": ("PER", 0.99), ...}
        self.longest_chunk = 0

    def __call__(self, chunks):
        out = []
        for chunk in chunks:
            self.longest_chunk = max(self.longest_chunk, len(chunk))
            ents = []
            for name, (group, score) in self.table.items():
                for m in re.finditer(re.escape(name), chunk):
                    ents.append({"entity_group": group, "score": score,
                                 "start": m.start(), "end": m.end(), "word": name})
            out.append(ents)
        return out


def run(text, table, counts=None, vault=None):
    engine = PrivacyEngine(nlp=FakeNER(table))
    return engine.redact(text, counts or {}, vault or {})


class LabelMapping(unittest.TestCase):
    def test_person_and_location(self):
        r = run("Hi I am Ritvik from Vellore", {"Ritvik": ("PER", .99), "Vellore": ("LOC", .99)})
        self.assertEqual(r["redacted"], "Hi I am <PERSON_1> from <LOCATION_1>")

    def test_org_gets_its_own_tag(self):
        r = run("I work at Google", {"Google": ("ORG", .99)})
        self.assertEqual(r["redacted"], "I work at <ORG_1>")

    def test_person_named_like_a_company_is_still_redacted(self):
        # The model calls "Tata" an ORG, but it could be a person. Fail safe: redact it.
        r = run("My friend Tata called me", {"Tata": ("ORG", .90)})
        self.assertNotIn("Tata", r["redacted"])

    def test_misc_is_left_alone(self):
        r = run("I am Indian", {"Indian": ("MISC", .99)})
        self.assertEqual(r["redacted"], "I am Indian")


class CodeHandling(unittest.TestCase):
    def test_low_confidence_in_code_line_is_ignored(self):
        r = run("import Flask", {"Flask": ("ORG", .60)})
        self.assertEqual(r["redacted"], "import Flask")

    def test_name_in_code_line_is_caught_when_confident(self):
        # The old rule skipped NER for any text containing 'def ', so Priya leaked.
        r = run("def foo(): # my friend Priya's number is 9876543210", {"Priya": ("PER", .97)})
        self.assertNotIn("Priya", r["redacted"])
        self.assertNotIn("9876543210", r["redacted"])

    def test_fenced_block_low_confidence_ignored(self):
        text = "```\nx = Alice\n```"
        self.assertEqual(run(text, {"Alice": ("PER", .60)})["redacted"], text)

    def test_name_in_prose_next_to_code_is_caught(self):
        text = "Here is my code:\n```\nx = 1\n```\nThanks, Priya"
        self.assertNotIn("Priya", run(text, {"Priya": ("PER", .60)})["redacted"])


class Robustness(unittest.TestCase):
    def test_long_text_is_chunked_and_offsets_stay_correct(self):
        text = "\n".join(["lorem ipsum dolor sit amet"] * 300) + "\nHi I am Ritvik"
        engine = PrivacyEngine(nlp=FakeNER({"Ritvik": ("PER", .99)}))
        r = engine.redact(text, {}, {})
        self.assertTrue(r["redacted"].endswith("Hi I am <PERSON_1>"))
        self.assertLessEqual(engine.nlp_manager.longest_chunk, MAX_CHUNK_CHARS)

    def test_one_huge_line_is_split(self):
        engine = PrivacyEngine(nlp=FakeNER({}))
        engine.redact("word " * 2000, {}, {})
        self.assertLessEqual(engine.nlp_manager.longest_chunk, MAX_CHUNK_CHARS)

    def test_entity_inside_an_existing_tag_is_ignored(self):
        r = run("My PAN is ABCDE1234F", {"PAN_CARD": ("ORG", .90)})
        self.assertEqual(r["redacted"], "My PAN is <PAN_CARD_1>")


class Consistency(unittest.TestCase):
    def test_same_name_keeps_its_tag_across_messages(self):
        table = {"Ritvik": ("PER", .99), "Asha": ("PER", .99)}
        first = run("I am Ritvik", table)
        second = run("Ritvik and Asha", table, first["updated_counts"], first["vault"])
        self.assertEqual(second["redacted"], "<PERSON_1> and <PERSON_2>")


NO_NER = {}   # these tests only exercise the regex layer


class Checksums(unittest.TestCase):
    def test_known_vectors(self):
        from validators import luhn_valid, verhoeff_valid
        self.assertTrue(verhoeff_valid("2363"))
        self.assertFalse(verhoeff_valid("2364"))
        self.assertTrue(luhn_valid("4111111111111111"))
        self.assertFalse(luhn_valid("4111111111111112"))

    def test_valid_card_is_redacted_as_a_card_not_aadhaar(self):
        r = run("Card 4111 1111 1111 1111 please", NO_NER)
        self.assertEqual(r["redacted"], "Card <CREDIT_CARD_1> please")

    def test_long_number_failing_luhn_is_left_alone(self):
        r = run("Order 4111 1111 1111 1112 shipped", NO_NER)
        self.assertEqual(r["redacted"], "Order 4111 1111 1111 1112 shipped")

    def test_grouped_aadhaar_is_always_redacted(self):
        r = run("Aadhaar 2345 6789 0125", NO_NER)           # checksum invalid, shape is distinctive
        self.assertEqual(r["redacted"], "Aadhaar <IN_AADHAAR_1>")

    def test_bare_12_digits_need_a_valid_checksum(self):
        self.assertEqual(run("id 234567890124", NO_NER)["redacted"], "id <IN_AADHAAR_1>")   # valid
        self.assertEqual(run("id 234567890125", NO_NER)["redacted"], "id 234567890125")    # invalid


class Secrets(unittest.TestCase):
    def test_sk_prefix_is_part_of_the_secret(self):
        r = run("key sk-abcdefghijklmnop1234", NO_NER)
        self.assertEqual(r["redacted"], "key <SECRET_TOKEN_1>")

    def test_keyword_with_prefixed_key(self):
        r = run("api_key=sk-abcdefghijklmnop1234", NO_NER)
        self.assertEqual(r["redacted"], "api_key=<SECRET_TOKEN_1>")

    def test_short_password_in_a_sentence(self):
        r = run("my password is hunter2", NO_NER)
        self.assertEqual(r["redacted"], "my password is <SECRET_TOKEN_1>")

    def test_short_password_with_colon(self):
        r = run("password: Abc@1234", NO_NER)
        self.assertEqual(r["redacted"], "password: <SECRET_TOKEN_1>")

    def test_code_and_plain_english_are_not_mangled(self):
        self.assertEqual(run("password = get_password()", NO_NER)["redacted"], "password = get_password()")
        self.assertEqual(run("the password is required", NO_NER)["redacted"], "the password is required")


class RegexGapsFromTheEvalSet(unittest.TestCase):
    """Each test here comes from a failure the evaluation set exposed."""

    def test_landline_numbers(self):
        self.assertEqual(run("call 044-2345 6789", NO_NER)["redacted"], "call <PHONE_NUMBER_1>")
        self.assertEqual(run("call 011-23456789", NO_NER)["redacted"], "call <PHONE_NUMBER_1>")

    def test_ip_needs_valid_octets_and_is_not_a_version(self):
        self.assertEqual(run("ping 10.0.0.12", NO_NER)["redacted"], "ping <IP_ADDRESS_1>")
        self.assertEqual(run("dev 10.0.0.1", NO_NER)["redacted"], "dev <IP_ADDRESS_1>")      # 'dev' ends in v, still an IP
        self.assertEqual(run("upgrade to build 2.4.18.3", NO_NER)["redacted"], "upgrade to build 2.4.18.3")
        self.assertEqual(run("version 1.2.3.4 released", NO_NER)["redacted"], "version 1.2.3.4 released")
        self.assertEqual(run("bad 999.1.1.1", NO_NER)["redacted"], "bad 999.1.1.1")

    def test_jwt_is_redacted_whole(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk"
        self.assertEqual(run("Authorization: Bearer " + jwt, NO_NER)["redacted"], "Authorization: Bearer <SECRET_TOKEN_1>")

    def test_known_secret_formats(self):
        self.assertEqual(run("AWS key AKIAIOSFODNN7EXAMPLE", NO_NER)["redacted"], "AWS key <SECRET_TOKEN_1>")
        self.assertEqual(run("Use ghp_1234567890abcdefghijklmnopqrstuvwxyz now", NO_NER)["redacted"], "Use <SECRET_TOKEN_1> now")
        self.assertEqual(run("slack xoxb-1234567890-abcdefghij", NO_NER)["redacted"], "slack <SECRET_TOKEN_1>")


class NerFragments(unittest.TestCase):
    def test_fragment_inside_a_word_is_ignored_and_leaves_no_vault_entry(self):
        # BERT tagged 'ad' inside 'aadhaar' as an organization during the real evaluation.
        r = run("aadhaar number", {"ad": ("ORG", .90)})
        self.assertEqual(r["redacted"], "aadhaar number")
        self.assertEqual(r["vault"], {})
        self.assertEqual(r["updated_counts"], {})

    def test_whole_word_with_possessive_is_still_caught(self):
        self.assertEqual(run("Priya's phone", {"Priya": ("PER", .99)})["redacted"], "<PERSON_1>'s phone")


if __name__ == "__main__":
    unittest.main()
