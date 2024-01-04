import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 11
LOOT_LOOP = 12
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
    lib.rightStep(0.05)
    lib.downJumpAttack()
    # wait landing
    lib.delay(0.2)
    lib.doubleJumpAttackHuntingDecree()
    lib.tribleJumpAttack()
    lib.tribleJumpAttack()
    # wait to originPoint
    lib.delay(0.58)
