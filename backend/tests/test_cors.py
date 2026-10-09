"""CORS policy tests for the local server (uses a fake engine, so no BERT needed).

Needs httpx for FastAPI's TestClient. With the pinned fastapi 0.109 use:  pip install "httpx<0.28"
Run from the backend folder:  python -m unittest discover -s tests -v
"""
import os
import sys
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from fastapi.testclient import TestClient
    HAVE_CLIENT = True
except Exception:          # httpx or fastapi missing
    HAVE_CLIENT = False


@unittest.skipUnless(HAVE_CLIENT, "needs fastapi and httpx installed")
class CorsPolicy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # main.py builds the real BERT engine at import time; swap in a fake module first.
        class FakeEngine:
            def redact(self, text, current_counts, current_vault):
                return {"redacted": text.upper(), "vault": current_vault, "updated_counts": current_counts}
        fake = types.ModuleType("engine")
        fake.PrivacyEngine = FakeEngine
        sys.modules["engine"] = fake
        sys.modules.pop("main", None)
        import main
        cls.client = TestClient(main.app)

    EXT = "chrome-extension://" + "a" * 32
    EVIL = "https://evil.example.com"

    def test_extension_origin_is_allowed(self):
        r = self.client.get("/", headers={"Origin": self.EXT})
        self.assertEqual(r.headers.get("access-control-allow-origin"), self.EXT)

    def test_website_origin_is_not_allowed(self):
        r = self.client.get("/", headers={"Origin": self.EVIL})
        self.assertIsNone(r.headers.get("access-control-allow-origin"))

    def test_preflight_from_website_is_rejected(self):
        r = self.client.options("/redact", headers={
            "Origin": self.EVIL, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        self.assertNotEqual(r.status_code, 200)
        self.assertIsNone(r.headers.get("access-control-allow-origin"))

    def test_preflight_from_extension_is_accepted(self):
        r = self.client.options("/redact", headers={
            "Origin": self.EXT, "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.headers.get("access-control-allow-origin"), self.EXT)

    def test_redact_endpoint_still_works(self):
        r = self.client.post("/redact", json={"text": "hi"})
        self.assertEqual(r.json()["data"]["redacted"], "HI")

    def test_lookalike_extension_origin_is_rejected(self):
        for origin in ("chrome-extension://short", "chrome-extension://" + "A" * 32, "chrome-extension://" + "a" * 33):
            r = self.client.get("/", headers={"Origin": origin})
            self.assertIsNone(r.headers.get("access-control-allow-origin"), origin)


if __name__ == "__main__":
    unittest.main()
