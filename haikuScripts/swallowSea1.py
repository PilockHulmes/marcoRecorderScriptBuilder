import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib

time.sleep(3)

BUFF_LOOP = 11
LOOT_LOOP = 11
HUNT_LOOP = 2
BLOOM_LOOP = 3
loopCounter = 0

totemInterval = 400 # 8 mins
totem = lib.callWithInterval(lib.totem, totemInterval)
while True:
    totem()
    lib.right()
    # if loopCounter % HUNT_LOOP == 1:
    #     lib.doubleJumpAttackHuntingDecree()
    # else:
    #     lib.doubleJumpAttack()
    lib.flashJumpAttackHuntingDecree()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.leftUpImpaleRush()
    lib.delay(0.1)
    lib.left()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.delay(0.1)
    # if loopCounter % BLOOM_LOOP == 1:
    #     lib.aetherBloom()
    # lib.groundAttack()
    # lib.left()
    # lib.groundAttack()
    # lib.doubleJumpAttack()
    # lib.groundAttack()
