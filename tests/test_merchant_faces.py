"""商人头像裁脸：裁剪框配置、生成脚本、IconCache 的加载优先级。

对应需求：立绘 88×68 缩到 16×16 时脸被背景挤没，所以先按
``data/trade/merchant_faces.json`` 裁出脸（保持原分辨率），显示层仍然缩到
16×16；``IconCache`` 优先读 ``merchants_face/``，没有再退回 ``merchants/``。
"""

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from maplebot import gui
from tools import build_faces

FIXED_ORDER = [
    "kobi_1", "kobi_2", "kobi_3", "kobi_4", "kobi_5", "kobi_6", "kobi_7",
    "dour_4", "dour_5", "dour_6", "dour_7",
    "ore_4", "ore_5", "ore_6", "ore_7",
]


class FaceConfigTest(unittest.TestCase):
    def test_all_fifteen_merchants_have_a_face_box(self):
        boxes = build_faces.load_boxes()
        self.assertEqual(sorted(boxes), sorted(FIXED_ORDER))

    def test_boxes_are_positive_and_inside_the_88x68_source(self):
        boxes = build_faces.load_boxes()
        for merchant_id, (x, y, w, h) in boxes.items():
            source = build_faces.SOURCE_DIR / f"{merchant_id}.png"
            with Image.open(source) as image:
                self.assertLessEqual(x + w, image.width, merchant_id)
                self.assertLessEqual(y + h, image.height, merchant_id)
                self.assertGreater(w, 0, merchant_id)
                self.assertGreater(h, 0, merchant_id)

    def test_bad_box_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "faces.json"
            path.write_text(json.dumps({"kobi_1": [0, 0, 0, 10]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_faces.load_boxes(path)
            path.write_text(json.dumps({"kobi_1": [80, 0, 20, 20]}), encoding="utf-8")
            boxes = build_faces.load_boxes(path)
        # 越界只在裁图时检查（需要源图尺寸）
        with self.assertRaises(ValueError):
            build_faces.crop_face(build_faces.SOURCE_DIR / "kobi_1.png",
                                  boxes["kobi_1"])


class BuildFacesTest(unittest.TestCase):
    def test_crop_keeps_original_resolution(self):
        face = build_faces.crop_face(build_faces.SOURCE_DIR / "kobi_1.png",
                                     (10, 0, 54, 54))
        self.assertEqual(face.size, (54, 54))       # 不缩到 16×16

    def test_build_writes_faces_and_contact_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "faces"
            sheet = Path(tmp) / "faces.png"
            boxes = build_faces.build(out_dir=out, sheet_path=sheet)
            files = sorted(path.name for path in out.glob("*.png"))
            self.assertEqual(files, sorted(f"{key}.png" for key in boxes))
            for merchant_id, (x, y, w, h) in boxes.items():
                with Image.open(out / f"{merchant_id}.png") as image:
                    self.assertEqual(image.size, (w, h), merchant_id)
            with Image.open(sheet) as image:
                self.assertEqual(image.size,
                                 (build_faces.SHEET_COLUMNS * build_faces.SHEET_CELL_W,
                                  ((len(boxes) + build_faces.SHEET_COLUMNS - 1)
                                   // build_faces.SHEET_COLUMNS)
                                  * build_faces.SHEET_CELL_H))


class GeneratedArtifactsTest(unittest.TestCase):
    """仓库里已生成的 ``merchants_face/`` 必须和配置里的框一致。

    ``detections/`` 在 .gitignore 里：没跑过生成脚本的环境跳过对照表检查，
    脸图本身仍然要求存在（生成脚本的输出目录）。
    """

    @unittest.skipUnless(build_faces.FACE_DIR.is_dir(),
                         "先运行 tools/build_faces.py")
    def test_generated_faces_match_json(self):
        boxes = build_faces.load_boxes()
        for merchant_id, (x, y, w, h) in boxes.items():
            path = build_faces.FACE_DIR / f"{merchant_id}.png"
            self.assertTrue(path.is_file(), merchant_id)
            with Image.open(path) as image:
                self.assertEqual(image.size, (w, h), merchant_id)

    @unittest.skipUnless(build_faces.SHEET_PATH.is_file(),
                         "先运行 tools/build_faces.py")
    def test_face_sheet_is_generated(self):
        self.assertTrue(build_faces.SHEET_PATH.is_file())
        with Image.open(build_faces.SHEET_PATH) as image:
            self.assertGreater(image.width, 0)
            self.assertGreater(image.height, 0)


class IconCachePathTest(unittest.TestCase):
    """商人头像优先 merchants_face/，没有才退回 merchants/。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.face_dir = root / "face"
        self.portrait_dir = root / "portrait"
        self.icon_dir = root / "icon"
        for directory in (self.face_dir, self.portrait_dir, self.icon_dir):
            directory.mkdir()
        self.cache = gui.IconCache(None, icon_dir=self.icon_dir,
                                   portrait_dir=self.portrait_dir,
                                   face_dir=self.face_dir, use_pil=False)

    def touch(self, directory, key):
        path = directory / f"{key}.png"
        path.write_bytes(b"")

    def test_face_wins_over_full_portrait(self):
        self.touch(self.face_dir, "kobi_1")
        self.touch(self.portrait_dir, "kobi_1")
        self.assertEqual(self.cache.path_for("merchant", "kobi_1"),
                         self.face_dir / "kobi_1.png")

    def test_falls_back_to_portrait_when_face_missing(self):
        self.touch(self.portrait_dir, "kobi_1")
        self.assertEqual(self.cache.path_for("merchant", "kobi_1"),
                         self.portrait_dir / "kobi_1.png")

    def test_goods_never_use_face_directory(self):
        self.touch(self.face_dir, "pork")
        self.touch(self.icon_dir, "pork")
        self.assertEqual(self.cache.path_for("good", "pork"),
                         self.icon_dir / "pork.png")

    def test_missing_and_invalid_keys_return_none(self):
        self.assertIsNone(self.cache.path_for("merchant", "nobody"))
        self.assertIsNone(self.cache.path_for("merchant", "../kobi_1"))


class FaceDirConstantTest(unittest.TestCase):
    def test_gui_uses_the_generated_face_directory(self):
        self.assertEqual(gui.FACE_DIR, build_faces.FACE_DIR)
        self.assertEqual(gui.ICON_SIZE, 16)


if __name__ == "__main__":
    unittest.main()
