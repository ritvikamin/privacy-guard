from transformers import pipeline
import re

class PrivacyEngine:
    def __init__(self):
        print("--- [Privacy Guard] Initializing Global-Consistency Engine ---")
        # BERT-large is powerful. We only need one pass for accuracy.
        self.nlp_manager = pipeline(
            "ner", 
            model="dbmdz/bert-large-cased-finetuned-conll03-english",
            aggregation_strategy="simple"
        )

    def redact(self, text: str, current_counts: dict, current_vault: dict):
        # 1. PRE-CLEAN: Normalize newlines to prevent formatting drift
        output_text = text.replace("\r\n", "\n").replace("\u00a0", " ")
        
        full_vault = current_vault.copy() 
        tag_counts = current_counts.copy()

        # PERFORMANCE HACK: If it's a code block, skip the heavy AI step
        code_indicators = ["#include", "int main", "std::", "using namespace", "{", "}", "import ", "def "]
        is_code = any(indicator in output_text for indicator in code_indicators)

        # Helper to manage indexing and vaulting
        def apply_redaction(original_val, tag_base):
            nonlocal output_text
            val_clean = original_val.strip()
            if not val_clean: return
            
            # CROSS-BUBBLE CHECK: Search if this exists in the Global Vault
            existing_tag = next((tag for tag, val in full_vault.items() if val.lower() == val_clean.lower()), None)
            
            if existing_tag:
                target_tag = existing_tag
            else:
                tag_counts[tag_base] = tag_counts.get(tag_base, 0) + 1
                target_tag = f"<{tag_base}_{tag_counts[tag_base]}>"
                full_vault[target_tag] = val_clean
            
            # Use lookarounds to protect code symbols (like semicolons or brackets)
            safe_val = re.escape(val_clean)
            if tag_base in ["PERSON", "LOCATION"]:
                pattern = rf"(?<!\w){safe_val}(?!\w)"
            else:
                pattern = safe_val
            
            output_text = re.sub(pattern, target_tag, output_text)

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

        for m in re.finditer(r"\b[2-9]{1}[0-9]{3}\s[0-9]{4}\s[0-9]{4}\b", output_text):
            apply_redaction(m.group(), "IN_AADHAAR")

        phone_pattern = r"(?:\+91|91|0)?[\s-]?[6-9]\d{4}[\s-]?\d{5}\b"
        for m in reversed(list(re.finditer(phone_pattern, output_text))):
            apply_redaction(m.group(), "PHONE_NUMBER")
            
        # Updated Token Pattern to catch 'bearer', 'sk-', 'pk-', and generic 'token' keys
        token_pattern = r"(?i)(?:token|api_key|password|secret|bearer|sk-|pk-)[:=]?\s?['\"]?([a-zA-Z0-9\-_]{12,})['\"]?"
        for m in reversed(list(re.finditer(token_pattern, output_text))):
            apply_redaction(m.group(1), "SECRET_TOKEN")

        # IP Address Pattern
        for m in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", output_text):
            apply_redaction(m.group(), "IP_ADDRESS")
            
        # --- STEP 2: AI (Names & Locations) ---
        if not is_code:
            # FIXED: One single pass only. No .title() call.
            ner_results = self.nlp_manager(output_text)
            
            words_to_redact = set()
            for entity in ner_results:
                word = entity['word'].replace("##", "").strip()
                # 0.40 score threshold for better portfolio-grade accuracy
                if len(word) > 1 and entity['score'] > 0.40:
                    word_clean = word.lower()
                    if word_clean in ["email", "address", "phone", "number", "aadhaar", "pan", "card"]:
                        continue
                    label = "PERSON" if entity['entity_group'] in ["PER", "ORG"] else "LOCATION"
                    words_to_redact.add((word, label))

            sorted_ai = sorted(list(words_to_redact), key=lambda x: len(x[0]), reverse=True)
            for word, tag in sorted_ai:
                apply_redaction(word, tag)
        else:
            print("--- [Privacy Guard] Heuristic Code Match. Skipping AI inference for speed. ---")

        return {
            "redacted": output_text, 
            "vault": full_vault, 
            "updated_counts": tag_counts
        }