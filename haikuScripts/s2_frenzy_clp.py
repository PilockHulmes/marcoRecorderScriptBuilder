import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time
from returnToPoint import Return

time.sleep(3)

BUFF_LOOP = 9
LOOT_LOOP = 9
SWORD_LOOP = 1
BLOOM_LOOP = 2
ADJUST_LOOP = 2
TOTEM_LOOP = 50
SLEEP_INTERVAL = 0.1
loopCounter = 0

r = Return()
r.start()
time.sleep(1)
r.save()

lib.totem()
lib.check()

while True:
    r.botTesting()
    r.returnToSavePoint()
    if (loopCounter + 1) % TOTEM_LOOP == 0:
        lib.totem()
    # if (loopCounter + 1) % SWORD_LOOP == 0:
    #     lib.huntingDecree()
    # if (loopCounter + 1) % BLOOM_LOOP == 0:
    #     lib.aetherBloom()
    loopCounter += 1

    pydirectinput.keyDown("left")
    for i in range(30):
        pydirectinput.keyDown("f")
    pydirectinput.keyUp("left")
    time.sleep(0.1)
    pydirectinput.keyDown("right")
    for i in range(30):
        pydirectinput.keyDown("f")
    pydirectinput.keyUp("right")
    time.sleep(0.1)