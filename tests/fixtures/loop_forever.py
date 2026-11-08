"""测试用假脚本：不碰游戏、不注入按键，只循环 sleep。

用来验证 `run.py` 的 `--stop-after` / 急停补丁能停下任意 `while True`。
"""

import time

print("[fixture] started")
count = 0
while True:
    count += 1
    time.sleep(0.05)
    if count % 20 == 0:
        print(f"[fixture] tick {count}")
