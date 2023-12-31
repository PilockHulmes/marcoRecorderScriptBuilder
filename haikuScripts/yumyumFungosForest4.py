import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

while True:
    for i in range(10):
        lib.keyboardPress("right")
        lib.jumpAttack()
        lib.slash()
        lib.keyboardRelease("right")
        lib.keyboardPress("left")
        lib.jumpAttack()
        lib.slash()
        lib.keyboardRelease("left")
    lib.sellAllEquips()