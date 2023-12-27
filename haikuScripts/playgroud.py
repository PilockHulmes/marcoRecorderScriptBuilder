import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

while True:
    for i in range(10):
        lib.right()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.left()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
        lib.jumpAttack()
    lib.sellAllEquips()
