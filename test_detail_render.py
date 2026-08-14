import unittest
import json
import os
import urllib.request
import re

class TestDetailRender(unittest.TestCase):
    def test_catalog_rendering_fields(self):
        apps = []
        # Try fetching from active server
        for port in [8001, 8000]:
            try:
                req = urllib.request.Request(f"http://localhost:{port}/")
                with urllib.request.urlopen(req, timeout=3) as r:
                    if r.status == 200:
                        html = r.read().decode("utf-8", errors="replace")
                        m = re.search(r'var CATALOG_APPS = (.*?);\n', html, re.S) or re.search(r'var CATALOG_APPS = (.*?);', html, re.S)
                        if m:
                            data = json.loads(m.group(1))
                            apps = data.get("apps", [])
                            break
            except Exception:
                continue

        if not apps:
            cat_path = "central/static/catalog.json" if os.path.exists("central/static/catalog.json") else "static/catalog.json"
            self.assertTrue(os.path.exists(cat_path))
            with open(cat_path, encoding="utf-8") as f:
                data = json.load(f)
                apps = data.get("apps", [])

        self.assertGreater(len(apps), 0)
        n8n = next((a for a in apps if a["id"] == "n8n"), None)
        self.assertIsNotNone(n8n)

        # Ensure no apps are missing critical description or category fields
        missing_desc = [a["id"] for a in apps if not a.get("long_description") and not a.get("description")]
        self.assertEqual(len(missing_desc), 0, f"Apps missing description: {missing_desc}")

if __name__ == "__main__":
    unittest.main()
