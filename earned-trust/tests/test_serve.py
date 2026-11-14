"""The server over real HTTP: static files, the case list, decisions, and requests it must refuse."""

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from trust import decisions, serve

DOSSIER = {"case": {"issue": "T1", "label": "REQ-T1", "title": "Test case", "language": "Java"},
           "refusals": [{"id": "R1", "owner": {"name": "Aino"}, "options": ["keep", "drop"], "evidence": []}],
           "units": [], "owners": {"approver": {"name": "Sara"}}, "id": "d1",
           "summary": {"cleared": 0, "units": 0, "lines_to_read": 0, "lines_changed": 0, "checks_hold": 0,
                       "checks": 0, "tests_run": 0, "tests": 0}, "findings": []}


class Server(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        (root / "dossier").mkdir()
        (root / "dossier" / "t1.json").write_text(json.dumps(DOSSIER))
        (root / "web" / "js").mkdir(parents=True)
        (root / "web" / "index.html").write_text("<html>page</html>")
        (root / "web" / "js" / "app.js").write_text("// app")
        (root / "secret.txt").write_text("secret")
        for target, name in ((serve, "ROOT"), (decisions, "ROOT")):
            patch = mock.patch.object(target, name, root)
            patch.start()
            self.addCleanup(patch.stop)
        patch = mock.patch.object(serve, "WEB", root / "web")
        patch.start()
        self.addCleanup(patch.stop)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), serve.Handler)
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)
        self.url = f"http://127.0.0.1:{self.http.server_port}"

    def get(self, path):
        with urllib.request.urlopen(self.url + path) as r:
            return r.headers["Content-Type"], r.read().decode()

    def post(self, body):
        req = urllib.request.Request(self.url + "/api/decide", data=json.dumps(body).encode(), method="POST")
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())

    def test_static_files_are_served_with_their_type(self):
        self.assertEqual(self.get("/js/app.js"), ("text/javascript", "// app"))
        self.assertEqual(self.get("/")[1], "<html>page</html>")

    def test_paths_outside_web_never_leave_it(self):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/js/../../secret.txt"):
            self.assertNotIn("secret", self.get(path)[1], path)

    def test_the_case_list_counts_open_decisions(self):
        cases = json.loads(self.get("/api/cases")[1])
        self.assertEqual(cases, [{"id": "t1", "label": "REQ-T1", "title": "Test case", "language": "Java", "open": 1, "outcome": None}])

    def test_a_decision_is_recorded_and_returned_in_the_new_state(self):
        state = self.post({"case": "t1", "item": "R1", "decision": "keep"})
        self.assertEqual(state["decisions"]["R1"]["by"]["name"], "Aino")
        self.assertEqual(json.loads(self.get("/api/cases")[1])[0]["open"], 0)

    def test_invalid_decisions_get_400_and_change_nothing(self):
        for body in ({"case": "t1", "item": "R1", "decision": "nonsense"}, {"case": "t1", "item": "MERGE", "decision": "approved"},
                     {"case": "nope", "item": "R1", "decision": "keep"}, {"case": "t1"}):
            with self.assertRaises(urllib.error.HTTPError) as err:
                self.post(body)
            self.assertEqual(err.exception.code, 400, body)
            err.exception.close()
        self.assertEqual(decisions.load("t1"), [])


if __name__ == "__main__":
    unittest.main()
