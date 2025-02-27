# import time
# from returnToPoint import Return
# from botCheckSolver import BotSolver
# import commandBuilderLib as lib
# import pydirectinput
# import detection
# from PIL import Image

# from khali import commands as lib

# time.sleep(1)

# lib.janus()

# lib.hold("left", 0.1)

import time

def test_sleep(duration, trials=100):
    deltas = []
    for _ in range(trials):
        start = time.perf_counter()
        time.sleep(duration)
        end = time.perf_counter()
        deltas.append((end - start) * 1000)  # 转换为毫秒

    avg = sum(deltas) / trials
    print(f"目标休眠 {duration*1000:.3f} ms，实际平均 {avg:.3f} ms，波动范围 {min(deltas):.3f}~{max(deltas):.3f} ms")

test_sleep(0.35)  # 测试 1 毫秒的休眠

# lib.dash(times=3)

# for i in range(5):
#     lib.click("g")
#     lib.click("g")
#     lib.click("f")
#     time.sleep(0.33)

# lib.ring()
# lib.faceDirection("left")

# r = Return()
# r.start()

# time.sleep(20)

# r.solveRune()

# r.returnToRunePoint()

# lib.inputText("Hello World S21Rpt")

# b = BotSolver(r.capture)

# b.debug()

# b.needSolveRune()

# image = r.capture.frame

# enhanced = detection.image_enhance(image)
# c = Image.fromarray(enhanced)
# c.save("z_enhanced.png")

# print(b.getBotText())