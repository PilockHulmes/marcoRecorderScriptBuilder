import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 19
LOOT_LOOP = 11
HUNTING_DECREE_LOOP = 2
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
    if loopCounter % HUNTING_DECREE_LOOP == 0:
        lib.doubleJumpAttackHuntingDecree()
    else:
        lib.doubleJumpAttack()
    lib.downJumpAttack()
    # landing
    # lib.delay(0.1)
    lib.downJumpAttack()
    # landing
    lib.delay(0.1)
    lib.right()
    lib.downJumpAttack()
    # return
    lib.delay(0.15)