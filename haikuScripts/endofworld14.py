import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time

time.sleep(3)

BUFF_LOOP = 10
LOOT_LOOP = 10
loopCounter = 0

lib.totem()
while True:
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
    if loopCounter % LOOT_LOOP == 0:
        lib.sellAllEquips()
    loopCounter += 1
    # lib.left()
    pydirectinput.press("left")
    lib.jumpAttack()
    lib.groundAttack()
    pydirectinput.press("right")
    lib.jumpAttack()
    lib.groundAttack()