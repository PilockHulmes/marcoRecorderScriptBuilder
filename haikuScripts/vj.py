import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib


totemInterval = 480 # 8 mins
totem = lib.callWithInterval(lib.totem, totemInterval)


import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
from returnToPoint import Return

r = Return()
r.start()
time.sleep(1)
r.save()

while True:
    totem()
    r.botTesting()
    # r.returnToSavePoint()
    lib.right()
    lib.doubleJumpAttackHuntingDecree()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.left()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    # lib.sellAllEquips()
    time.sleep(0.5)
