import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

while True:
    lib.totem()
    for i in range(10):
        lib.right()
        lib.doubleJumpAttackHuntingDecree()
        lib.doubleJumpAttackHuntingDecree()
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
        lib.doubleJumpAttack()
    lib.sellAllEquips()
    lib.delay(0.5)