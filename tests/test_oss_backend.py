import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from maplebot import oss_backend


def record(merchant_id="dour_4", price=19):
    return {"v": 1, "merchant_id": merchant_id, "map": "孤獨的沙漠-1",
            "writer": "me", "rev": 1,
            "rows": {"water|sell": {"p": price, "t": 1.0, "r": 300}}}


class RelayHandler(BaseHTTPRequestHandler):
    """假的中转函数：按类属性决定返回什么。"""

    status = 200
    payload = {"ok": True}
    last_body = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).last_body = self.rfile.read(length)
        body = json.dumps(type(self).payload).encode("utf-8")
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class RelayBackendTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), RelayHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/upload"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def make(self, **overrides):
        config = {"bucket": "b", "token": "tok", "upload_url": self.url,
                  "read_prefix": ""}
        config.update(overrides)
        backend = oss_backend.OssBackend(config)
        backend._auth = object()          # 假装有直连凭证，走 direct 分支会被拦住
        backend._auth = None
        return backend

    def test_relay_upload_sends_token_and_record(self):
        RelayHandler.status, RelayHandler.payload = 200, {"ok": True}
        backend = self.make()
        self.assertTrue(backend.put_if_match("dour_4", record(), None))
        sent = json.loads(RelayHandler.last_body.decode("utf-8"))
        self.assertEqual(sent["token"], "tok")
        self.assertEqual(sent["merchant_id"], "dour_4")
        self.assertEqual(sent["record"]["rows"]["water|sell"]["p"], 19)

    def test_conflict_returns_false(self):
        RelayHandler.status, RelayHandler.payload = 409, {"ok": False}
        backend = self.make()
        self.assertFalse(backend.put_if_match("dour_4", record(), '"x"'))

    def test_rate_limit_raises_429(self):
        RelayHandler.status, RelayHandler.payload = 429, {"ok": False}
        backend = self.make()
        with self.assertRaises(IOError) as ctx:
            backend.put_if_match("dour_4", record(), None)
        self.assertIn("429", str(ctx.exception))

    def test_missing_upload_url_raises(self):
        backend = self.make(upload_url="")
        with self.assertRaises(IOError):
            backend.put_if_match("dour_4", record(), None)


class PublicReadTest(unittest.TestCase):
    def make(self, index):
        backend = oss_backend.OssBackend({"bucket": "b", "token": "t",
                                          "read_prefix": "http://example/"})
        backend._get_public = lambda key: index.get(key)
        return backend

    def test_list_reads_index(self):
        backend = self.make({"index.json": {"dour_4": '"1"', "kobi_1": '"2"'}})
        self.assertEqual(backend.list_objects(), {"dour_4": '"1"', "kobi_1": '"2"'})

    def test_get_reads_object(self):
        backend = self.make({"merchants/dour_4.json": record()})
        obj, _etag = backend.get("dour_4")
        self.assertEqual(obj["rows"]["water|sell"]["p"], 19)

    def test_missing_object_returns_none(self):
        backend = self.make({})
        self.assertEqual(backend.get("nope"), (None, None))


if __name__ == "__main__":
    unittest.main()
