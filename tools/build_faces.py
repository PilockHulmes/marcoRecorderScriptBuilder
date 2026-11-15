"""把商人立绘裁成脸部图，并生成人眼检查用的对照表。

``data/trade/merchants/<id>.png`` 是 88×68 的商店立绘截图：边框、角色身体和
货舱 UI 都在里面，直接缩到 16×16 时脸会被背景挤没。每张脸的裁剪框记录在
``data/trade/merchant_faces.json``（``{"kobi_1": [x, y, w, h], ...}``），这里：

1. 按框从 ``merchants/`` 裁出**原分辨率**的脸（不缩放，显示层再缩到 16×16）；
2. 写到 ``data/trade/merchants_face/``，文件名与商人 id 相同；
3. 生成 ``detections/face_sheet.png``：15 张脸排成 5×3 网格，每格左边是
   裁图放大、右边是 16×16 的最终显示效果，方便检查有没有裁歪。

运行::

    .\\venv\\Scripts\\python.exe tools\\build_faces.py
"""

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
FACE_CONFIG = ROOT / "data" / "trade" / "merchant_faces.json"
SOURCE_DIR = ROOT / "data" / "trade" / "merchants"
FACE_DIR = ROOT / "data" / "trade" / "merchants_face"
SHEET_PATH = ROOT / "detections" / "face_sheet.png"

#: 对照表：每格 = 裁图预览 + 最终 16×16 效果；5 列正好 3 行放下 15 个商人
SHEET_COLUMNS = 5
SHEET_FACE = 96          # 裁图预览边长
SHEET_DISPLAY = 48       # 16×16 放大 3 倍后的边长
SHEET_CELL_W = 160
SHEET_CELL_H = 146
SHEET_MARGIN = 6
SHEET_LABEL_H = 20

LINE_ORDER = {"kobi": 0, "dour": 1, "ore": 2}


def _sort_key(merchant_id):
    """与看板一致：先线路（kobi < dour < ore），再数字序号。"""
    prefix, _, suffix = str(merchant_id).partition("_")
    try:
        number = int(suffix)
    except (TypeError, ValueError):
        number = 10 ** 9
    return (LINE_ORDER.get(prefix, len(LINE_ORDER)), number, str(merchant_id))


def load_boxes(path=None):
    """读裁剪框 -> ``{merchant_id: (x, y, w, h)}``，并校验是四个整数。"""
    raw = json.loads(Path(path or FACE_CONFIG).read_text(encoding="utf-8"))
    boxes = {}
    for merchant_id, value in raw.items():
        if not isinstance(value, list) or len(value) != 4:
            raise ValueError(f"{merchant_id}: 裁剪框必须是 [x, y, w, h]，实际 {value!r}")
        x, y, w, h = (int(item) for item in value)
        if w <= 0 or h <= 0:
            raise ValueError(f"{merchant_id}: 宽高必须为正，实际 {w}×{h}")
        boxes[str(merchant_id)] = (x, y, w, h)
    return boxes


def crop_face(source, box):
    """按 ``(x, y, w, h)`` 裁一张脸（保持原分辨率，不缩到 16）。"""
    x, y, w, h = (int(item) for item in box)
    with Image.open(str(source)) as image:
        image = image.convert("RGB")
        if x < 0 or y < 0 or x + w > image.width or y + h > image.height:
            raise ValueError(
                f"{source}: 裁剪框 {(x, y, w, h)} 超出图片 {image.width}×{image.height}")
        return image.crop((x, y, x + w, y + h))


def build(face_config=FACE_CONFIG, source_dir=SOURCE_DIR, out_dir=FACE_DIR,
          sheet_path=SHEET_PATH):
    """照 ``merchant_faces.json`` 生成全部脸图 + 对照表；返回裁剪框字典。"""
    boxes = load_boxes(face_config)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    faces = {}
    for merchant_id, box in boxes.items():
        source = Path(source_dir) / f"{merchant_id}.png"
        if not source.is_file():
            raise FileNotFoundError(source)
        face = crop_face(source, box)
        face.save(out_dir / f"{merchant_id}.png")
        faces[merchant_id] = face
    if sheet_path:
        write_sheet(faces, boxes, sheet_path)
    return boxes


def write_sheet(faces, boxes, path, columns=SHEET_COLUMNS):
    """把裁好的脸排成网格；左大图看裁剪，右小图看 16×16 最终效果。"""
    keys = sorted(faces, key=_sort_key)
    columns = max(1, int(columns))
    rows = (len(keys) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * SHEET_CELL_W, rows * SHEET_CELL_H),
                      (245, 245, 245))
    draw = ImageDraw.Draw(sheet)
    for index, merchant_id in enumerate(keys):
        x = (index % columns) * SHEET_CELL_W
        y = (index // columns) * SHEET_CELL_H
        face = faces[merchant_id]
        preview = face.resize((SHEET_FACE, SHEET_FACE), Image.LANCZOS)
        sheet.paste(preview, (x + SHEET_MARGIN, y + SHEET_LABEL_H + SHEET_MARGIN))
        # 最终显示尺寸只有 16×16：按 LANCZOS 缩到 16 再最近邻放大，所见即所得
        tiny = face.resize((16, 16), Image.LANCZOS).resize(
            (SHEET_DISPLAY, SHEET_DISPLAY), Image.NEAREST)
        sheet.paste(tiny, (x + SHEET_MARGIN + SHEET_FACE + 12,
                           y + SHEET_LABEL_H + SHEET_MARGIN))
        draw.text((x + SHEET_MARGIN, y + 4),
                  f"{merchant_id}  {list(boxes.get(merchant_id, ()))}",
                  fill=(0, 0, 0))
        draw.text((x + SHEET_MARGIN + SHEET_FACE + 12,
                   y + SHEET_LABEL_H + SHEET_MARGIN + SHEET_DISPLAY + 4),
                  "16x16", fill=(0, 0, 0))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(path)
    return path


def main():
    boxes = build()
    print(f"裁剪 {len(boxes)} 张脸 -> {FACE_DIR}")
    for merchant_id, box in sorted(boxes.items(), key=lambda item: _sort_key(item[0])):
        print(f"  {merchant_id}: {list(box)}")
    print(f"对照表 -> {SHEET_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
