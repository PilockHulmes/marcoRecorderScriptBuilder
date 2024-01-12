import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time

time.sleep(3)

BUFF_LOOP = 3
LOOT_LOOP = 2
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
    lib.aetherBloom()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.leftImpaleRush()
    lib.huntingDecree()
    lib.huntingDecree()
    lib.huntingDecree()
    lib.delay(0.1)
    lib.nobleSummons()
    lib.delay(0.1)
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.jumpRightDownImpaleRush()
    lib.right()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.left()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.delay(0.4)
    end = time.time()
    print("Whole run: ", end - start)