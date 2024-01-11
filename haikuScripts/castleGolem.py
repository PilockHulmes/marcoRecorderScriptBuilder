import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import random

time.sleep(3)

BUFF_LOOP = 50
LOOT_LOOP_LOW = 40
LOOT_LOOP_HIGH = 50
loopCounter = 0

lib.totem()

sellOrNot = lib.sellRandomly(LOOT_LOOP_LOW, LOOT_LOOP_HIGH)

while True:
    if loopCounter % BUFF_LOOP == 0:
        lib.buffSharpEyes()
        lib.buffDsi()
    if sellOrNot():
        lib.sellAllEquips()
    # for i in range(random.randint(50, 60)):
    #     lib.jumpAttack()
    #     lib.delayRandomly(0.2)
    
    lib.right()
    lib.cleave()
    lib.delayRandomly(0.2)
    lib.left()
    lib.cleave()
    lib.delayRandomly(0.2)