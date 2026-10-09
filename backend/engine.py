import bisect
import re

from validators import luhn_valid, verhoeff_valid

NER_MODEL = "dbmdz/bert-large-cased-finetuned-conll03-english"

# What we do with each label the NER model can return.
#   PER  -> <PERSON_n>
#   ORG  -> <ORG_n>      (names and companies overlap, e.g. "Tata", so we redact ORG too,
#                         but keep it a separate tag so the LLM still knows it is a company)
#   LOC  -> <LOCATION_n>
#   MISC (nationalities, languages, events) is deliberately absent: almost all false positives.
LABEL_MAP = {"PER": "PERSON", "ORG": "ORG", "LOC": "LOCATION"}

NER_THRESHOLD = 0.40        # normal prose lines
NER_THRESHOLD_CODE = 0.85   # code-looking lines: only very confident names (comments, strings)
MAX_CHUNK_CHARS = 1000      # BERT reads at most 512 tokens, so feed it small pieces

# Words the model sometimes tags that are really just our own field names.
SKIP_WORDS = {"email", "address", "phone", "number", "aadhaar", "pan", "card"}

# A line "looks like code" if it starts with a code keyword, or ends with ; { }, or has => / std::
CODE_LINE = re.compile(
    r"^\s*(?:#include|import\s|from\s+\S+\s+import|def\s|class\s|return\b|function\b|const\s|let\s|var\s"
    r"|public\s|private\s|using\s+namespace|int\s+main|@\w+)|[{};]\s*$|std::|=>"
)

# 'the password is required' should not redact 'required'
PASSWORD_STOPWORDS = {"required", "incorrect", "wrong", "invalid", "correct", "empty", "missing", "weak", "strong", "expired"}

# Secrets with a recognisable shape (what secret scanners look for). Run BEFORE the generic keyword rule.
SECRET_FORMATS = [
    r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}",   # JWT (3 dot-separated parts)
    r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",                                       # AWS access key id
    r"\bgh[pousr]_[A-Za-z0-9]{36,}",                                         # GitHub token
    r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",                                     # Slack token
    r"\bAIza[0-9A-Za-z_\-]{35}",                                            # Google API key
]

TAG_PATTERN = re.compile(r"<[A-Z_]+_\d+>")


class PrivacyEngine:
    def __init__(self, nlp=None):
        """`nlp` can be any callable that takes a list of strings and returns, for each string,
        a list of entity dicts (entity_group, score, start, end). Tests pass a fake one;
        normally we load the real BERT model."""
        print("--- [Privacy Guard] Initializing Global-Consistency Engine ---")
        if nlp is None:
            from transformers import pipeline   # imported here so tests do not need torch
            nlp = pipeline("ner", model=NER_MODEL, aggregation_strategy="simple")
        self.nlp_manager = nlp

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _classify_lines(text):
        """[(start, end, is_code)] for every line. Lines inside ``` fences, and lines that
        look like code, are marked as code."""
        spans, pos, in_fence = [], 0, False
        for line in text.split("\n"):
            start, end = pos, pos + len(line)
            pos = end + 1
            if line.lstrip().startswith("```"):
                in_fence = not in_fence
                spans.append((start, end, True))
            else:
                spans.append((start, end, in_fence or bool(CODE_LINE.search(line))))
        return spans

    @staticmethod
    def _chunk_spans(lines):
        """Group lines into (start, end) pieces of at most MAX_CHUNK_CHARS, cutting at line
        boundaries where possible. A single huge line is cut into fixed-size pieces."""
        spans, a, b = [], None, None
        for start, end, _ in lines:
            if end - start > MAX_CHUNK_CHARS:
                if a is not None:
                    spans.append((a, b))
                    a = b = None
                for s in range(start, end, MAX_CHUNK_CHARS):
                    spans.append((s, min(s + MAX_CHUNK_CHARS, end)))
            elif a is None:
                a, b = start, end
            elif end - a <= MAX_CHUNK_CHARS:
                b = end
            else:
                spans.append((a, b))
                a, b = start, end
        if a is not None:
            spans.append((a, b))
        return spans

    def _find_entities(self, text):
        """Run NER over the text and return a set of (word, label) worth redacting."""
        lines = self._classify_lines(text)
        starts = [l[0] for l in lines]
        tag_spans = [m.span() for m in TAG_PATTERN.finditer(text)]

        chunks = [(a, b) for a, b in self._chunk_spans(lines) if text[a:b].strip()]
        if not chunks:
            return set()
        results = self.nlp_manager([text[a:b] for a, b in chunks])

        found = set()
        for (a, _), entities in zip(chunks, results):
            for ent in entities:
                label = LABEL_MAP.get(ent["entity_group"])
                if label is None:                      # MISC and anything unknown
                    continue
                s, e = a + ent["start"], a + ent["end"]
                word = text[s:e].strip()
                if len(word) < 2 or word.lower() in SKIP_WORDS:
                    continue
                # BERT sometimes tags a piece INSIDE a word ('ad' in 'aadhaar'); that is not a real entity.
                if (s > 0 and text[s - 1].isalnum()) or (e < len(text) and text[e].isalnum()):
                    continue
                if any(s < te and e > ts for ts, te in tag_spans):   # part of a tag we already made
                    continue
                is_code = lines[bisect.bisect_right(starts, s) - 1][2]
                if ent["score"] > (NER_THRESHOLD_CODE if is_code else NER_THRESHOLD):
                    found.add((word, label))
        return found

    # ------------------------------------------------------------------ main entry
    def redact(self, text: str, current_counts: dict, current_vault: dict):
        # 1. PRE-CLEAN: Normalize newlines to prevent formatting drift
        output_text = text.replace("\r\n", "\n").replace(" ", " ")

        full_vault = current_vault.copy()
        tag_counts = current_counts.copy()

        # Helper to manage indexing and vaulting
        def apply_redaction(original_val, tag_base):
            nonlocal output_text
            val_clean = original_val.strip()
            if not val_clean: return

            # CROSS-BUBBLE CHECK: Search if this exists in the Global Vault
            existing_tag = next((tag for tag, val in full_vault.items() if val.lower() == val_clean.lower()), None)

            if existing_tag:
                target_tag, new_number = existing_tag, None
            else:
                new_number = tag_counts.get(tag_base, 0) + 1
                target_tag = f"<{tag_base}_{new_number}>"

            # Use lookarounds to protect code symbols (like semicolons or brackets)
            safe_val = re.escape(val_clean)
            if tag_base in ["PERSON", "ORG", "LOCATION"]:
                pattern = rf"(?<!\w){safe_val}(?!\w)"
            else:
                pattern = safe_val

            replaced_text, n_replaced = re.subn(pattern, target_tag, output_text)
            if n_replaced == 0:
                return          # nothing matched: do not create a vault entry or bump the counter
            output_text = replaced_text
            if new_number is not None:
                tag_counts[tag_base] = new_number
                full_vault[target_tag] = val_clean

        # --- STEP 0: URI & TECHNICAL ---
        # Updated URI pattern: Excludes quotes and semicolons at the end
        uri_pattern = r"\b(?:mongodb\+srv|https?|ftp|ssh):\/\/[^\s\"';]+"
        for m in reversed(list(re.finditer(uri_pattern, output_text, re.IGNORECASE))):
            apply_redaction(m.group(), "URI_RESOURCE")

        # --- STEP 1: REGEX (Emails, PAN, Aadhaar, Phone, Tokens) ---
        for m in re.finditer(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", output_text):
            apply_redaction(m.group(), "EMAIL_ADDRESS")

        for m in re.finditer(r"\b[A-Z]{5}[0-9]{4}[A-Z]{1}\b", output_text, re.IGNORECASE):
            apply_redaction(m.group(), "PAN_CARD")

        # Payment cards FIRST, and only if the Luhn checksum passes. Otherwise a 16-digit card would be
        # half-eaten as a 12-digit Aadhaar, and any long number (order IDs...) would be redacted.
        for m in re.finditer(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)", output_text):
            digits = re.sub(r"\D", "", m.group())
            if 13 <= len(digits) <= 19 and luhn_valid(digits):
                apply_redaction(m.group(), "CREDIT_CARD")

        # Aadhaar: 12 digits, optionally grouped 4-4-4 with spaces or hyphens, and NOT part of a longer number.
        #   grouped (1234 5678 9012)  -> the shape is distinctive, always redact
        #   bare 12 digits            -> ambiguous (could be an order ID), redact only if Verhoeff passes
        for m in re.finditer(r"(?<!\d)(?<!\d[ -])[2-9]\d{3}([ -]?)\d{4}\1\d{4}(?![ -]?\d)", output_text):
            digits = re.sub(r"\D", "", m.group())
            if m.group(1) or verhoeff_valid(digits):
                apply_redaction(m.group(), "IN_AADHAAR")

        phone_pattern = r"(?:\+91|91|0)?[\s-]?[6-9]\d{4}[\s-]?\d{5}\b"
        for m in reversed(list(re.finditer(phone_pattern, output_text))):
            apply_redaction(m.group(), "PHONE_NUMBER")

        # Landlines: STD code + number, e.g. 044-2345 6789 or 011-23456789
        for m in reversed(list(re.finditer(r"(?<![\w])0\d{2,4}[ -]\d{3,4}[ -]?\d{3,4}(?!\d)", output_text))):
            apply_redaction(m.group(), "PHONE_NUMBER")

        for pattern in SECRET_FORMATS:
            for m in reversed(list(re.finditer(pattern, output_text))):
                apply_redaction(m.group(), "SECRET_TOKEN")

        # Prefixed API keys (sk-..., pk-...): the prefix is part of the secret, so redact the whole key.
        for m in reversed(list(re.finditer(r"\b(?:sk|pk)-[A-Za-z0-9_\-]{12,}", output_text))):
            apply_redaction(m.group(), "SECRET_TOKEN")

        # Keyword followed by a long value: token=..., api_key: ..., bearer ...
        token_pattern = r"(?i)(?:token|api_key|password|secret|bearer)[:=]?\s?['\"]?([a-zA-Z0-9\-_]{12,})['\"]?"
        for m in reversed(list(re.finditer(token_pattern, output_text))):
            apply_redaction(m.group(1), "SECRET_TOKEN")

        # Passwords can be short, so catch them when introduced by 'is', ':' or '='.
        # The value must end at whitespace/quote/end, so code like `password = get_password()` is left alone.
        password_pattern = r"(?i)\b(?:password|passwd|pwd)\b\s*(?:is\b|[:=])\s*['\"]?([^\s'\",;()\[\]{}]{4,})(?=[\s'\",;]|$)"
        for m in reversed(list(re.finditer(password_pattern, output_text))):
            if m.group(1).lower() not in PASSWORD_STOPWORDS:
                apply_redaction(m.group(1), "SECRET_TOKEN")

        # IP Address Pattern
        for m in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", output_text):
            if any(int(octet) > 255 for octet in m.group().split(".")):
                continue                                   # 999.1.1.1 is not an IP
            before = output_text[max(0, m.start() - 12):m.start()].lower()
            if re.search(r"(?:\b(?:version|build|release|ver)\.?|\bv)\s*$", before):
                continue                                   # 'build 2.4.18.3' is a version number
            apply_redaction(m.group(), "IP_ADDRESS")

        # --- STEP 2: AI (Names, Organizations, Locations) ---
        # Runs on ALL text. Code-looking lines are not skipped, just held to a higher confidence bar.
        found = self._find_entities(output_text)
        for word, tag in sorted(found, key=lambda x: len(x[0]), reverse=True):
            apply_redaction(word, tag)

        return {
            "redacted": output_text,
            "vault": full_vault,
            "updated_counts": tag_counts
        }
