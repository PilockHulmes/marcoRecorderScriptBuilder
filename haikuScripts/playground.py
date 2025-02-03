import time
from returnToPoint import Return
from botCheckSolver import BotSolver
import commandBuilderLib as lib
import pydirectinput

r = Return()
r.start()

# time.sleep(2)

b = BotSolver(r.capture)

# b.debug()

# b.needSolveRune()

print(b.getBotText())