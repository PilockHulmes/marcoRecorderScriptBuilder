import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

# lib.doubleJump()
# time.sleep(1)
# lib.doubleJump()
# time.sleep(1)
# lib.doubleJump()
# time.sleep(1)

while True:
    lib.totem()
    for i in range(10):
        lib.left()
        lib.doubleJumpAttackHuntingDecree()
        lib.doubleJumpAttackHuntingDecree()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.right()
        lib.doubleJumpAttack()
        lib.left()
        lib.doubleHighJumpAttact()
        lib.right()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        lib.aetherBloom()
        lib.doubleJumpAttack()
        lib.doubleJumpAttack()
        # wait for landing
        lib.delay(0.2)
    lib.sellAllEquips()