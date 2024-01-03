import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 12

lib.totem()
counter = 0
while True:
    for i in range(6):
        if counter % BUFF_LOOP == 0:
            lib.buffSharpEyes()
            lib.buffDsi()
            lib.buffHs()
            counter = 0
        counter += 1
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
    lib.delay(0.3)