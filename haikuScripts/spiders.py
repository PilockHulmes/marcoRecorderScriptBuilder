import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 13
LOOT_LOOP = 6
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
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.leftUpImpaleRush()
    # wait landing
    lib.delay(0.3)
    lib.aetherBloom()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.groundAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    # wait landing
    lib.delay(0.5)