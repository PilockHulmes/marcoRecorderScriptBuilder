import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time
from returnToPoint import Return

r = Return()
r.start()
time.sleep(1)
r.save()

time.sleep(2)

r.solveRune()

# while True:
#     time.sleep(2)
#     r.solveRune()