import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 12
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
    lib.right()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.tribleJumpAttack()
    lib.tribleJumpAttack()
    lib.tribleJumpAttack()
    lib.doubleJumpAttack()
    lib.groundAttack()
    lib.left()
    lib.flashJumpAttack()
    # landing
    lib.delay(0.2)
    lib.tribleJumpAttack()
    lib.tribleJumpAttack()
    lib.tribleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.doubleJumpAttack()
    lib.flashJumpAttack()
    lib.delay(0.2)