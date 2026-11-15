"""h20.ship: the GitLab project of a remote URL, and a merge request posted to GitLab REST (a local server stands in)."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from harness.utils.git.gitlab import GitLabError, call, open_mr, project_of


class Fake(BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append((self.path, self.headers.get("PRIVATE-TOKEN"), body))
        code = 409 if body.get("title") == "taken" else 201
        self.send_response(code)
        self.end_headers()
        self.wfile.write(json.dumps({"iid": 3, "web_url": "https://gl/g/p/-/merge_requests/3"}).encode())

    def log_message(self, *args):
        pass


class GitLabTest(unittest.TestCase):
    def test_the_project_of_a_remote(self):
        for url in ("https://gitlab.example.com/group/sub/proj.git", "git@gitlab.example.com:group/sub/proj.git",
                    "https://oauth2:tok@gitlab.example.com/group/sub/proj", "ssh://git@gitlab.example.com:2222/group/sub/proj.git"):
            with self.subTest(url=url):
                self.assertEqual(project_of(url), ("https://gitlab.example.com/api/v4", "group/sub/proj"))
        with self.assertRaises(GitLabError):
            project_of("/local/path")

    def test_a_merge_request_is_posted_with_the_token(self):
        server = HTTPServer(("127.0.0.1", 0), Fake)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        api = f"http://127.0.0.1:{server.server_port}/api/v4"
        mr = open_mr(api, "group/p", "work", "main", "Set X", "body", token="t0k")
        self.assertEqual(mr["iid"], 3)
        path, token, body = Fake.seen[-1]
        self.assertEqual((path, token, body["source_branch"], body["target_branch"]),
                         ("/api/v4/projects/group%2Fp/merge_requests", "t0k", "work", "main"))
        with self.assertRaises(GitLabError) as caught:
            open_mr(api, "group/p", "work", "main", "taken", "body", token="t0k")
        self.assertIn("409", str(caught.exception))
        with self.assertRaises(GitLabError):
            call("GET", "http://127.0.0.1:1/x", token="")


if __name__ == "__main__":
    unittest.main()
