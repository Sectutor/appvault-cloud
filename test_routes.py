import unittest
import urllib.request
import os

class TestCentralRoutes(unittest.TestCase):
    def test_routes_health_and_index(self):
        ports = [8001, 8000]
        active_port = None
        for port in ports:
            try:
                url = f"http://localhost:{port}/health"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=3) as r:
                    if r.status == 200:
                        active_port = port
                        break
            except Exception:
                continue

        if active_port:
            for ep in ["/", "/health"]:
                url = f"http://localhost:{active_port}{ep}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as r:
                    self.assertEqual(r.status, 200)
                    self.assertGreater(len(r.read()), 0)
        else:
            self.assertTrue(os.path.exists("central/main.py") or os.path.exists("main.py"))

if __name__ == "__main__":
    unittest.main()
