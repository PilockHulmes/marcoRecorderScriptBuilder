"""maplebot.rune_api 的单元测试：凭据读取、图片编码、回复解析、请求构造。

不会真的请求网络：请求部分注入一个假的 OpenAI 兼容客户端。
"""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import cv2
import numpy as np

from maplebot import rune_api
from maplebot.rune_api import (
    Credentials,
    RuneAPIError,
    RuneConfigError,
    RuneSolveError,
    RuneSolver,
)


def write_tmp(text, name="deepseek.local.json"):
    tmp = tempfile.TemporaryDirectory(prefix="rune-creds-")
    path = Path(tmp.name) / name
    path.write_text(text, encoding="utf-8")
    return tmp, path


class CredentialsTest(unittest.TestCase):
    def test_full_json(self):
        tmp, path = write_tmp(json.dumps({
            "api_key": "sk-test",
            "base_url": "https://example.invalid",
            "model": "some-model",
        }))
        self.addCleanup(tmp.cleanup)
        creds = rune_api.load_credentials(path)
        self.assertEqual(creds, Credentials("sk-test", "https://example.invalid", "some-model"))

    def test_json_defaults_are_filled(self):
        tmp, path = write_tmp('{"api_key": "sk-test"}')
        self.addCleanup(tmp.cleanup)
        creds = rune_api.load_credentials(path)
        self.assertEqual(creds.base_url, rune_api.DEFAULT_BASE_URL)
        self.assertEqual(creds.model, rune_api.DEFAULT_MODEL)

    def test_raw_key_text(self):
        tmp, path = write_tmp("sk-raw-key\n")
        self.addCleanup(tmp.cleanup)
        creds = rune_api.load_credentials(path)
        self.assertEqual(creds.api_key, "sk-raw-key")
        self.assertEqual(creds.model, rune_api.DEFAULT_MODEL)

    def test_utf8_bom_is_tolerated(self):
        tmp = tempfile.TemporaryDirectory(prefix="rune-creds-")
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "deepseek.local.json"
        path.write_bytes(b"\xef\xbb\xbf" + json.dumps({"api_key": "sk-bom"}).encode("utf-8"))
        self.assertEqual(rune_api.load_credentials(path).api_key, "sk-bom")

    def test_empty_api_key_is_rejected(self):
        tmp, path = write_tmp('{"api_key": "   "}')
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(RuneConfigError) as ctx:
            rune_api.load_credentials(path)
        self.assertIn("api_key", str(ctx.exception))

    def test_empty_file_is_rejected(self):
        tmp, path = write_tmp("   \n")
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(RuneConfigError):
            rune_api.load_credentials(path)

    def test_missing_file_is_rejected(self):
        with self.assertRaises(RuneConfigError) as ctx:
            rune_api.load_credentials(Path(tempfile.gettempdir()) / "__no_such_creds__.json")
        self.assertIn("找不到密钥文件", str(ctx.exception))

    def test_invalid_json_is_rejected(self):
        tmp, path = write_tmp("{not json")
        self.addCleanup(tmp.cleanup)
        with self.assertRaises(RuneConfigError) as ctx:
            rune_api.load_credentials(path)
        self.assertIn("JSON", str(ctx.exception))


class EncodingTest(unittest.TestCase):
    def test_encode_png_produces_valid_png(self):
        image = np.zeros((30, 100, 3), np.uint8)
        image[:, :] = (0, 0, 255)  # 纯红（BGR）
        png = rune_api.encode_png(image)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        decoded = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape, image.shape)
        # cv2.imencode 写出的 PNG 颜色正确：BGR(0,0,255) → RGB 也是红
        self.assertGreaterEqual(int(decoded[0, 0, 2]), 200)
        self.assertLessEqual(int(decoded[0, 0, 0]), 50)

    def test_empty_image_is_rejected(self):
        with self.assertRaises(ValueError):
            rune_api.encode_png(np.zeros((0, 0, 3), np.uint8))

    def test_data_url_roundtrip(self):
        image = np.zeros((10, 10, 3), np.uint8)
        url = rune_api.to_data_url(rune_api.encode_png(image))
        self.assertTrue(url.startswith("data:image/png;base64,"))
        payload = base64.b64decode(url.split(",", 1)[1])
        self.assertTrue(payload.startswith(b"\x89PNG"))


class ParseArrowsTest(unittest.TestCase):
    def test_plain_json(self):
        self.assertEqual(
            rune_api.parse_arrows('{"arrows": ["down", "down", "left", "down"]}'),
            ["down", "down", "left", "down"],
        )

    def test_fenced_json(self):
        text = '```json\n{"arrows": ["up", "down", "left", "right"]}\n```'
        self.assertEqual(rune_api.parse_arrows(text), ["up", "down", "left", "right"])

    def test_prose_around_json(self):
        text = 'Sure! Here it is: {"arrows": ["up", "up", "up", "up"]} hope it helps'
        self.assertEqual(rune_api.parse_arrows(text), ["up"] * 4)

    def test_bare_list_is_accepted(self):
        self.assertEqual(rune_api.parse_arrows('["left", "left", "right", "right"]'),
                         ["left", "left", "right", "right"])

    def test_case_and_whitespace_are_normalized(self):
        self.assertEqual(rune_api.parse_arrows('{"arrows": [" UP ", "Down", "left ", "RIGHT"]}'),
                         ["up", "down", "left", "right"])

    def test_chinese_aliases(self):
        self.assertEqual(rune_api.parse_arrows('{"arrows": ["下", "上", "左", "右"]}'),
                         ["down", "up", "left", "right"])

    def test_arrow_glyph_aliases(self):
        self.assertEqual(rune_api.parse_arrows('{"arrows": ["↓", "↑", "←", "→"]}'),
                         ["down", "up", "left", "right"])

    def test_wrong_count_is_rejected(self):
        with self.assertRaises(RuneSolveError) as ctx:
            rune_api.parse_arrows('{"arrows": ["down", "up", "left"]}')
        self.assertIn("数量", str(ctx.exception))

    def test_illegal_direction_is_rejected(self):
        with self.assertRaises(RuneSolveError) as ctx:
            rune_api.parse_arrows('{"arrows": ["down", "diagonal", "left", "up"]}')
        self.assertIn("非法方向", str(ctx.exception))

    def test_empty_arrows_list_is_rejected(self):
        with self.assertRaises(RuneSolveError):
            rune_api.parse_arrows('{"arrows": []}')

    def test_model_reports_error(self):
        with self.assertRaises(RuneSolveError) as ctx:
            rune_api.parse_arrows('{"arrows": [], "error": "blurry image"}')
        self.assertIn("blurry image", str(ctx.exception))

    def test_missing_arrows_key(self):
        with self.assertRaises(RuneSolveError):
            rune_api.parse_arrows('{"result": "ok"}')

    def test_empty_content(self):
        for content in (None, "", "   \n"):
            with self.assertRaises(RuneSolveError):
                rune_api.parse_arrows(content)

    def test_garbage_content(self):
        with self.assertRaises(RuneSolveError):
            rune_api.parse_arrows("I cannot see any arrows in this image.")


class FakeCompletions:
    def __init__(self, content=None, exc=None):
        self.content = content
        self.exc = exc
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        message = SimpleNamespace(content=self.content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def fake_client(content=None, exc=None):
    completions = FakeCompletions(content=content, exc=exc)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


class SolverTest(unittest.TestCase):
    def setUp(self):
        self.image = np.zeros((60, 300, 3), np.uint8)
        self.creds = Credentials("sk-test")

    def test_solve_returns_directions(self):
        client, _ = fake_client('{"arrows": ["down", "down", "left", "down"]}')
        solver = RuneSolver(credentials=self.creds, client=client)
        self.assertEqual(solver.solve(self.image), ["down", "down", "left", "down"])

    def test_request_payload_contract(self):
        client, completions = fake_client('{"arrows": ["up", "up", "up", "up"]}')
        solver = RuneSolver(credentials=self.creds, client=client)
        solver.solve(self.image)
        kwargs = completions.calls[0]

        self.assertEqual(kwargs["model"], "deepseek-flash")
        self.assertEqual(kwargs["temperature"], 0)
        self.assertEqual(kwargs["max_tokens"], 200)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(kwargs["extra_body"], {"thinking": {"type": "disabled"}})

        system, user = kwargs["messages"]
        self.assertEqual(system["role"], "system")
        self.assertIn("four", system["content"])
        self.assertEqual(user["role"], "user")
        text_block, image_block = user["content"]
        self.assertEqual(text_block["type"], "text")
        self.assertEqual(image_block["type"], "image_url")
        self.assertEqual(image_block["image_url"]["detail"], "high")
        self.assertTrue(image_block["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_payload_is_recorded_for_debugging(self):
        client, _ = fake_client('{"arrows": ["up", "up", "up", "up"]}')
        solver = RuneSolver(credentials=self.creds, client=client)
        solver.solve(self.image)
        self.assertIsNotNone(solver.last_payload)
        self.assertEqual(solver.last_payload["model"], "deepseek-flash")

    def test_api_exception_is_wrapped(self):
        client, _ = fake_client(exc=RuntimeError("network down"))
        solver = RuneSolver(credentials=self.creds, client=client)
        with self.assertRaises(RuneAPIError) as ctx:
            solver.solve(self.image)
        self.assertIn("network down", str(ctx.exception))

    def test_bad_response_structure(self):
        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: object())))
        solver = RuneSolver(credentials=self.creds, client=client)
        with self.assertRaises(RuneAPIError):
            solver.solve(self.image)

    def test_parse_failure_surfaces_as_solve_error(self):
        client, _ = fake_client("no json here")
        solver = RuneSolver(credentials=self.creds, client=client)
        with self.assertRaises(RuneSolveError):
            solver.solve(self.image)

    def test_custom_model_and_base_url_are_used(self):
        client, completions = fake_client('{"arrows": ["up", "up", "up", "up"]}')
        creds = Credentials("sk-test", "https://example.invalid", "custom-model")
        solver = RuneSolver(credentials=creds, client=client)
        solver.solve(self.image)
        self.assertEqual(completions.calls[0]["model"], "custom-model")
        self.assertEqual(solver.credentials.base_url, "https://example.invalid")

    def test_missing_credentials_surface_at_init(self):
        with mock.patch.object(rune_api, "load_credentials", side_effect=RuneConfigError("no key")):
            with self.assertRaises(RuneConfigError):
                RuneSolver()

    def test_default_credentials_are_loaded_once(self):
        with mock.patch.object(rune_api, "load_credentials", return_value=self.creds) as loader:
            RuneSolver()
        loader.assert_called_once()


if __name__ == "__main__":
    unittest.main()
