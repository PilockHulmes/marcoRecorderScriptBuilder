import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time
from returnToPoint import Return

time.sleep(3)

BUFF_LOOP = 9
LOOT_LOOP = 9
ADJUST_LOOP = 2
loopCounter = 0

r = Return()
r.start()
time.sleep(1)
r.save()

lib.totem()

while True:
    if (loopCounter + 1) % ADJUST_LOOP == 0:
        r.returnToSavePoint()
    loopCounter += 1
    r.botTesting()
    # lib.left()
    lib.right()
    lib.groundAttack()
    lib.jumpAttack()
    time.sleep(0.5)
    lib.left()
    lib.groundAttack()
    lib.jumpAttack()
    time.sleep(0.5)