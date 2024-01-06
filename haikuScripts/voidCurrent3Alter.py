import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time

time.sleep(3)

BUFF_LOOP = 3
LOOT_LOOP = 3
loopCounter = 0

lib.totem()
while True:
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
    if loopCounter % LOOT_LOOP == 0:
        lib.sellAllEquips()
    loopCounter += 1
    start = time.time()
    lib.right()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.jumpLeftUpImpaleRush()
    lib.left()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.slowerFlashJumpAttack()
    lib.flashJumpAttack()
    lib.delay(0.2)
    lib.right()
    lib.flashJumpAttack()
    lib.rightImpaleRush()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.plummet()
    lib.delay(0.5)
    lib.left()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    end = time.time()
    print("Whole run: ", end - start)