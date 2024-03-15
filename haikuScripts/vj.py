import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

totemInterval = 480 # 8 mins
totem = lib.callWithInterval(lib.totem, totemInterval)

while True:
    totem()
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
    # lib.sellAllEquips()
    time.sleep(0.5)
