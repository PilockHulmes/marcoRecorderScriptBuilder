import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from maplebot import oss_backend


def record(merchant_id="dour_4", price=19):
    return {"v": 1, "merchant_id": merchant_id, "map": "孤獨的沙漠-1",
            "writer": "me", "rev": 1,
            "rows": {"water|sell": {"p": price, "t": 1.0, "r": 300}}}


class FakeOss(BaseHTTPRequestHandler):
    """同时扮演"中转函数"和"预签名直连"两个角色。"""

    objects = {"/merchants/dour_4.json": record()}
    index = {"/index.json": {"dour_4": '"1"'}}
    upload_status = 200
    upload_payload = {"ok": True}
    last_upload = None

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        type(self).last_upload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path.endswith("/bundle"):
            body = {"ok": True, "expires": 9_999_999_999,
                    "index_url": self.base() + "/index.json",
                    "objects": {"dour_4": {"url": self.base() + "/merchants/dour_4.json",
                                           "etag": '"1"'}}}
            return self.reply(200, body)
        return self.reply(type(self).upload_status, type(self).upload_payload)

    def do_GET(self):
        payload = type(self).objects.get(self.path) or type(self).index.get(self.path)
        if payload is None:
            return self.reply(404, {"error": "missing"})
        return self.reply(200, payload)

    def reply(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def base(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def log_message(self, *args):
        pass


class ProductionModeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeOss)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        base = f"http://127.0.0.1:{cls.server.server_port}"

        def clock():
            return 1000.0

        cls.backend = oss_backend.OssBackend(
            {"bucket": "b", "token": "tok", "upload_url": base + "/upload"},
            now=clock)
        # 走生产分支：没有直连凭证
        cls.backend._auth = None

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_bundle_url_is_derived_from_upload_url(self):
        self.assertEqual(self.backend.bundle_url,
                         f"http://127.0.0.1:{self.server.server_port}/bundle")

    def test_list_uses_signed_index(self):
        self.assertEqual(self.backend.list_objects(), {"dour_4": '"1"'})

    def test_get_uses_signed_object_url(self):
        obj, etag = self.backend.get("dour_4")
        self.assertEqual(obj["rows"]["water|sell"]["p"], 19)
        self.assertEqual(etag, '"1"')

    def test_upload_sends_token_and_etag(self):
        FakeOss.upload_status, FakeOss.upload_payload = 200, {"ok": True}
        self.assertTrue(self.backend.put_if_match("dour_4", record(), '"1"'))
        sent = FakeOss.last_upload
        self.assertEqual(sent["token"], "tok")
        self.assertEqual(sent["etag"], '"1"')
        self.assertEqual(sent["merchant_id"], "dour_4")

    def test_conflict_returns_false(self):
        FakeOss.upload_status, FakeOss.upload_payload = 409, {"ok": False}
        self.assertFalse(self.backend.put_if_match("dour_4", record(), '"stale"'))

    def test_rate_limit_raises(self):
        FakeOss.upload_status, FakeOss.upload_payload = 429, {"ok": False}
        with self.assertRaises(IOError) as ctx:
            self.backend.put_if_match("dour_4", record(), '"1"')
        self.assertIn("429", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
