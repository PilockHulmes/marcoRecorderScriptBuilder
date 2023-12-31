import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

while True:
    for i in range(10):
        lib.right()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.left()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
    lib.sellAllEquips()
