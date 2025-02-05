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
    if (loopCounter + 1) % ADJUST_LOOP == 0:
        # wait a bit longer to let character landing
        time.sleep(SLEEP_INTERVAL * 3)
        r.returnToSavePoint()
    if (loopCounter + 1) % TOTEM_LOOP == 0:
        lib.totem()
    # if (loopCounter + 1) % SWORD_LOOP == 0:
    #     lib.huntingDecree()
    # if (loopCounter + 1) % BLOOM_LOOP == 0:
    #     lib.aetherBloom()
    loopCounter += 1

    # pydirectinput.keyDown("left")
    # pydirectinput.press("f")
    # time.sleep(20)
    # pydirectinput.k("left")
    # pydirectinput.keyUp("f")
    # pydirectinput.keyDown("right")
    # pydirectinput.keyDown("f")
    # time.sleep(20)
    # pydirectinput.keyUp("right")
    # pydirectinput.keyUp("f")
    # time.sleep(0.1)

    lib.right()
    lib.groundAttack()
    lib.jumpAttack()
    lib.groundAttack()
    lib.jumpAttack()
    time.sleep(SLEEP_INTERVAL)
    lib.left()
    lib.groundAttack()
    lib.jumpAttack()
    lib.groundAttack()
    lib.jumpAttack()
    time.sleep(SLEEP_INTERVAL)