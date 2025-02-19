import time
from returnToPoint import Return
from botCheckSolver import BotSolver
import commandBuilderLib as lib
import pydirectinput
import detection
from PIL import Image

from khali import commands as lib

time.sleep(1)

# lib.dash(times=3)
lib.upJump()
lib.dashLeft(5)
lib.refresh()
time.sleep(1)
lib.jump()
lib.dashRight(5)
lib.refresh()

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