"""当前流水线的开销基准（可重复运行，不启动游戏）。

    .\\venv\\Scripts\\python.exe tests\\bench_pipeline.py            # 只测图像部分
    .\\venv\\Scripts\\python.exe tests\\bench_pipeline.py --ocr       # 加上 PaddleOCR（慢，约 15s）

用途：给「每帧都算所有识别」这件事一个可量化的基线，改架构后用同一套数字对比。

说明：
- 画面用合成噪声（matchTemplate 的耗时只取决于尺寸，与内容无关）；
- 模板用仓库里真实的 assets；
- 小地图尺寸取 260x180（按 1366x768 客户端上的常见值），可用 --minimap 改；
- 每一项跑 N 次取中位数，避免首帧抖动。
"""

import argparse
import statistics
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from maplebot import utils  # noqa: E402

ASSETS = ROOT / "haikuScripts" / "assets"


def load(name, color=False):
    path = ASSETS / name
    img = cv2.imread(str(path), cv2.IMREAD_COLOR if color else cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise SystemExit(f"模板读取失败：{path}")
    return img


def timeit(fn, repeat=30, warmup=3):
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimap", default="260x180", help="小地图尺寸，如 260x180")
    parser.add_argument("--frame", default="1366x768", help="整窗尺寸，如 1366x768")
    parser.add_argument("--ocr", action="store_true", help="额外测 PaddleOCR（很慢）")
    args = parser.parse_args()

    mw, mh = (int(x) for x in args.minimap.lower().split("x"))
    fw, fh = (int(x) for x in args.frame.lower().split("x"))

    rng = np.random.default_rng(0)
    frame = rng.integers(0, 256, (fh, fw, 3), dtype=np.uint8)
    minimap = frame[40:40 + mh, 40:40 + mw].copy()
    minimap_prev = np.roll(minimap, 1, axis=1)

    player = load("player_template.png")
    other = load("other_template.png")
    rune = load("rune_template.png")
    rune_buff = load("rune_buff_template.jpg")

    OTHER_RANGES = (((0, 245, 215), (10, 255, 255)),)
    RUNE_RANGES = (((141, 148, 245), (146, 158, 255)),)

    print(f"frame={fw}x{fh}  minimap={mw}x{mh}  templates: player{player.shape} other{other.shape} "
          f"rune{rune.shape} rune_buff{rune_buff.shape}")

    rows = []

    def add(name, fn, repeat=30):
        ms = timeit(fn, repeat=repeat)
        rows.append((name, ms))
        print(f"  {name:<44}{ms:8.3f} ms")

    # ---- 采屏 ----
    print("\n[采屏]")
    import mss

    window = {"left": 0, "top": 0, "width": fw, "height": fh}
    with mss.mss() as sct:
        monitor = sct.monitors[0]
        add("mss.grab(整个显示器)", lambda: sct.grab(monitor), repeat=20)
        add(f"mss.grab({fw}x{fh} 窗口区域)", lambda: sct.grab(window), repeat=20)
        raw = sct.grab(window)
        add("np.array(grab) 拷贝", lambda: np.array(raw), repeat=20)

    try:
        import dxcam

        camera = dxcam.create(output_color="BGR")
        if camera is not None:
            add("dxcam.grab(窗口区域)", lambda: camera.grab((0, 0, fw, fh)), repeat=20)
            camera.release()
        else:
            print("  dxcam 可用但没有输出设备，跳过")
    except Exception as exc:
        print(f"  dxcam 未安装/不可用（{type(exc).__name__}），跳过对比")

    # ---- 小地图识别 ----
    print("\n[小地图识别（每帧）]")
    add("multi_match(player, minimap)", lambda: utils.multi_match(minimap, player, 0.8))
    half = cv2.resize(minimap, (mw // 2, mh // 2), interpolation=cv2.INTER_AREA)
    half_player = cv2.resize(player, (max(1, player.shape[1] // 2), max(1, player.shape[0] // 2)), interpolation=cv2.INTER_AREA)
    add("multi_match(player, minimap/2)", lambda: utils.multi_match(half, half_player, 0.8))
    add("filter_color(minimap, OTHER)", lambda: utils.filter_color(minimap, OTHER_RANGES))
    filtered = utils.filter_color(minimap, OTHER_RANGES)
    add("multi_match(other, filtered)", lambda: utils.multi_match(filtered, other, 0.5))
    add("cvtColor(minimap) 灰度", lambda: cv2.cvtColor(minimap, cv2.COLOR_BGR2GRAY))
    add("absdiff(minimap, prev) 变化检测", lambda: cv2.absdiff(minimap, minimap_prev))

    # ---- 可选的整窗检测 ----
    print("\n[整窗检测（auto-maple 开着，haikuScripts 关着）]")
    add("cvtColor(frame) 全屏灰度", lambda: cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), repeat=20)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    add("count_nonzero(gray < 15) 黑屏", lambda: np.count_nonzero(gray < 15), repeat=20)
    top = frame[: fh // 8, :]
    add("multi_match(rune_buff, 顶部1/8)", lambda: utils.multi_match(top, rune_buff, 0.9), repeat=20)

    # ---- 组合：一帧 body ----
    print("\n[组合：一帧 _main 循环体]")

    def frame_body_haiku():
        mm = frame[40:40 + mh, 40:40 + mw]
        utils.multi_match(mm, player, 0.8)

    add("haikuScripts 现状（只找角色）", frame_body_haiku)

    def frame_body_automaple():
        mm = frame[40:40 + mh, 40:40 + mw]
        utils.multi_match(mm, player, 0.8)
        f = utils.filter_color(mm, RUNE_RANGES)
        utils.multi_match(f, rune, 0.9)
        f = utils.filter_color(mm, OTHER_RANGES)
        utils.multi_match(f, other, 0.5)
        g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        np.count_nonzero(g < 15)
        top = frame[: fh // 8, :]
        utils.multi_match(top, rune_buff, 0.9)

    add("auto-maple 现状（全部检测）", frame_body_automaple, repeat=20)

    # ---- OCR ----
    if args.ocr:
        print("\n[PaddleOCR 聊天框（每 2 秒一次）]")
        from paddleocr import PaddleOCR

        t0 = time.perf_counter()
        reader = PaddleOCR(lang="ch", show_log=False)
        init = time.perf_counter() - t0
        print(f"  {'PaddleOCR 初始化':<44}{init * 1000:8.1f} ms  (一次性)")
        chat = rng.integers(0, 256, (100, 400, 3), dtype=np.uint8)
        ms = timeit(lambda: reader.ocr(img=chat), repeat=3, warmup=1)
        print(f"  {'reader.ocr(100x400 聊天框)':<44}{ms:8.1f} ms")
        rows.append(("reader.ocr(聊天框)", ms))

    # ---- 汇总 ----
    print("\n[汇总：按 10fps 折算的单核占用]")
    for name, ms in rows:
        if name.startswith("haikuScripts") or name.startswith("auto-maple") or name.startswith("reader.ocr"):
            print(f"  {name:<44}{ms:8.2f} ms/次  ≈ 10 次/秒时占单核 {ms * 10:.0f}%")


if __name__ == "__main__":
    main()
