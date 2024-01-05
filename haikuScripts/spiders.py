import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 13
LOOT_LOOP = 5
loopCounter = 0

lib.totem()
while True:
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
    if loopCounter % LOOT_LOOP == 0:
        lib.sellAllEquips()
    loopCounter += 1
    lib.right()
    lib.doubleJumpAttack()
    lib.doubleJumpAttackHuntingDecree()
    lib.doubleJumpAttack()
    # old routine
    # lib.doubleJumpAttack()
    # lib.doubleJumpAttack()
    # lib.leftUpImpaleRush()
    # new routine
    lib.rightUpImpaleRush()
    # wait landing
    lib.delay(0.3)
    if loopCounter % 2 == 0:
        lib.aetherBloom()
    else:
        lib.nobleSummons()
    lib.leftStep()
    lib.doubleJumpAttack()
    lib.groundAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    # wait landing
    lib.delay(0.5)