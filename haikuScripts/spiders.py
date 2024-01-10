import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 13
LOOT_LOOP_LOW = 5
LOOT_LOOP_HIGH = 6
loopCounter = 0

lib.totem()

sellOrNot = lib.sellRandomly(LOOT_LOOP_LOW, LOOT_LOOP_HIGH)

while True:
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
    if sellOrNot():
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