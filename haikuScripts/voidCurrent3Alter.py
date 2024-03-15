import pyautogui
import pydirectinput
import time
import commandBuilderLib as lib
import time

time.sleep(3)

BUFF_LOOP = 3
LOOT_LOOP = 3
loopCounter = 0

totemInterval = 400 # 8 mins
totem = lib.callWithInterval(lib.totem, totemInterval)
while True:
    # if loopCounter % BUFF_LOOP == 0:
    #     lib.buffSharpEyes()
    #     lib.buffDsi()
    # if loopCounter % LOOT_LOOP == 0:
    #     lib.sellAllEquips()
    # loopCounter += 1
    start = time.time()
    totem()
    lib.right()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.jumpLeftUpImpaleRush()
    lib.left()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.summonBallWithInterval()
    lib.doubleJumpAttack()
    lib.delay(0.1)
    lib.huntingDecree()
    lib.huntingDecree()
    lib.huntingDecree()
    lib.flashJumpAttack()
    lib.groundAttack()
    lib.delay(0.1)
    lib.right()
    # lib.flashJumpAttack()
    # lib.rightImpaleRush()
    lib.downJumpAttack()
    lib.delay(0.3)
    # lib.right()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    # lib.doubleJumpAttack()
    # lib.doubleJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.aetherBloom()
    lib.delay(0.1)
    # lib.plummet()
    # lib.delay(0.5)
    lib.left()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    lib.flashJumpAttack()
    end = time.time()
    print("Whole run: ", end - start)