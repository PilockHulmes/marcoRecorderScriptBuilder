import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 11
LOOT_LOOP = 11
HUNT_LOOP = 2
BLOOM_LOOP = 3
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
    # if loopCounter % HUNT_LOOP == 1:
    #     lib.doubleJumpAttackHuntingDecree()
    # else:
    #     lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    # if loopCounter % BLOOM_LOOP == 1:
    #     lib.aetherBloom()
    lib.groundAttack()
    lib.left()
    lib.groundAttack()
    lib.doubleJumpAttack()
    lib.groundAttack()
