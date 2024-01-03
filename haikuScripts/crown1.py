import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 11
LOOT_LOOP = 4
loopCounter = 0

lib.totem()
while True:
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
        # lib.buffHs()
    if loopCounter % LOOT_LOOP == 0:
        lib.sellAllEquips()
    loopCounter += 1
    lib.left()
    lib.doubleJumpAttackHuntingDecree()
    lib.doubleJumpAttackHuntingDecree()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.right()
    lib.doubleJumpAttack()
    lib.left()
    lib.doubleHighJumpAttact()
    lib.right()
    lib.groundAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.aetherBloom()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    # wait for landing
    lib.delay(0.2)
