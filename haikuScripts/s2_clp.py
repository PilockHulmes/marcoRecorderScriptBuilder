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
TOTEM_LOOP = 50
SLEEP_INTERVAL = 0.3
loopCounter = 0

r = Return()
r.start()
time.sleep(1)
r.save()

lib.totem()

while True:
    if (loopCounter + 1) % ADJUST_LOOP == 0:
        r.returnToSavePoint()
    if (loopCounter + 1) % TOTEM_LOOP == 0:
        lib.totem()
    loopCounter += 1
    r.botTesting()
    # lib.left()
    lib.right()
    lib.groundAttack()
    lib.jumpAttack()
    time.sleep(SLEEP_INTERVAL)
    lib.left()
    lib.groundAttack()
    lib.jumpAttack()
    time.sleep(SLEEP_INTERVAL)