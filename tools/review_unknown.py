"""梳理 ``data/trade/icons_unknown/``：看看那些"认不出"的图标到底是谁。

下载下来的未知图标都是商店行里 63×63 的图标，所以可以直接和已知模板比对：
分数很高说明**图标其实是认识的**，只是当时的名字没查表（比如游戏写「貴族的布料」，
表里写「貴族的綢緞」）。那种情况只要补一个名字别名就能修好。

用法：

    .\\venv\\Scripts\\python.exe tools\\review_unknown.py
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

UNKNOWN = ROOT / "data" / "trade" / "icons_unknown"
ICONS = ROOT / "data" / "trade" / "icons"
NAMES = ROOT / "data" / "trade" / "good_names.json"

MATCH_MIN = 0.80


def load(path):
    return cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)


def main():
    if not UNKNOWN.exists():
        print("没有 icons_unknown 目录")
        return 0
    templates = {}
    for path in ICONS.glob("*.png"):
        img = load(path)
        if img is not None:
            templates[path.stem] = img
    names = json.loads(NAMES.read_text(encoding="utf-8")) if NAMES.exists() else {}

    files = sorted(UNKNOWN.glob("*.png"))
    print(f"未知图标 {len(files)} 张，已知模板 {len(templates)} 个\n")
    resolved = []
    for path in files:
        img = load(path)
        if img is None:
            continue
        best = (0.0, "")
        for good_id, tpl in templates.items():
            if tpl.shape[0] > img.shape[0] or tpl.shape[1] > img.shape[1]:
                continue
            score = float(cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED).max())
            if score > best[0]:
                best = (score, good_id)
        score, good_id = best
        sidecar = path.with_suffix(".txt")
        read_name = sidecar.read_text(encoding="utf-8").strip() if sidecar.exists() else ""
        if score >= MATCH_MIN:
            resolved.append((path.name, good_id, score, read_name))
            print(f"  {path.name}  ≈ {good_id} ({score:.3f})"
                  f"{'  当时读到：' + read_name if read_name else ''}")
        else:
            print(f"  {path.name}  没有匹配（{score:.3f}）"
                  f"{'  当时读到：' + read_name if read_name else ''}")

    if resolved:
        print(f"\n其中 {len(resolved)} 张其实认识，多半是**名字写法不同**：")
        missing = [r for r in resolved if r[3]]
        for file_name, good_id, score, read_name in resolved:
            if read_name and read_name not in names:
                print(f"  把 {read_name!r} 补成别名 -> {good_id}")
        if not missing:
            print("  （没有记录到当时读到的名字，无法自动补别名）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
