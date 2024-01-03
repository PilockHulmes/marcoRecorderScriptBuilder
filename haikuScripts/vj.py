import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

while True:
    lib.totem()
    for i in range(9):
        lib.right()
        lib.doubleJumpAttackHuntingDecree()
        lib.doubleJumpAttackHuntingDecree()
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
    time.sleep(1)
