import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

while True:
    for i in range(10):
        lib.keyboardPress("right")
        lib.jumpAttack()
        lib.cleave()
        lib.keyboardRelease("right")
        lib.keyboardPress("left")
        lib.jumpAttack()
        lib.cleave()
        lib.keyboardRelease("left")
    lib.sellAllEquips()