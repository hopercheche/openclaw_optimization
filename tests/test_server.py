import json
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from openclaw.server import build_server


class ServerTest(unittest.TestCase):
    def test_health_and_as2_architecture_endpoints(self) -> None:
        server = build_server("127.0.0.1", 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            host, port = server.server_address
            with urlopen(f"http://{host}:{port}/api/health", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["service"], "openclaw-audit-mvp")

            with urlopen(f"http://{host}:{port}/api/as2/architecture", timeout=3) as response:
                architecture_payload = json.loads(response.read().decode("utf-8"))
            self.assertIn("as2", architecture_payload)
            self.assertTrue(architecture_payload["architecture"]["agent_runtime_ready"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
