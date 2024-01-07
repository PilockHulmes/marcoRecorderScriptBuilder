import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 12
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
    lib.flashJumpAttackHuntingDecree()
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
    lib.delay(0.1)