import unittest
import urllib.request
import json
import os

class TestDetail(unittest.TestCase):
    def test_catalog_detail_data(self):
        # 1. Try to fetch from live running central server (8001 or 8000)
        html = None
        for port in [8001, 8000]:
            try:
                req = urllib.request.Request(f"http://localhost:{port}/")
                with urllib.request.urlopen(req, timeout=3) as r:
                    if r.status == 200:
                        html = r.read().decode("utf-8", errors="replace")
                        break
            except Exception:
                continue

        if html:
            self.assertIn("CATALOG_APPS", html)
            self.assertIn('"n8n"', html)
        else:
            # Fallback to inspecting static catalog file directly
            cat_path = "central/static/catalog.json" if os.path.exists("central/static/catalog.json") else "static/catalog.json"
            self.assertTrue(os.path.exists(cat_path))
            with open(cat_path, encoding="utf-8") as f:
                data = json.load(f)
                apps = data.get("apps", [])
                self.assertGreater(len(apps), 0)
                n8n = next((a for a in apps if a["id"] == "n8n"), None)
                self.assertIsNotNone(n8n)
                self.assertTrue("description" in n8n or "tagline" in n8n)

if __name__ == "__main__":
    unittest.main()
