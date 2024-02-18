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
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
    if loopCounter % LOOT_LOOP == 0:
        lib.sellAllEquips()
    if (loopCounter + 1) % ADJUST_LOOP == 0:
        r.returnToSavePoint()
    loopCounter += 1
    # lib.left()
    lib.right()
    lib.groundAttack()
    lib.tribleJumpAttack()
    time.sleep(0.1)
    lib.groundAttack()
    lib.left()
    lib.left()
    lib.groundAttack()
    lib.doubleJumpAttack()
    time.sleep(0.1)
    lib.groundAttack()
    time.sleep(0.05)