import pyautogui
import pydirectinput
import time
import random

LINE_DELIMITER = "\n"
INTERVAL_KEYUP = 0.01
INTERVAL_CLICK = 0.015
INTERVAL_JUMP = 0.06
INTERVAL_DOUBLE_JUMP_LANDING = 550 / 1000  # 同层跳跃落地间隔
INTERVAL_SLASH = 220 / 1000  # 穿刺动作长度
INTERVAL_SLASH_END = 600 / 1000  # 魔剑共鸣动作长度

def delay(ms):
    start_time = time.perf_counter()
    end_time = start_time + ms
    while time.perf_counter() < end_time:
        pass

delayTreshold = 0.07
def delayRandomly(ms):
    start_time = time.perf_counter()
    end_time = start_time + ms + random.uniform(0, delayTreshold)
    while time.perf_counter() < end_time:
        pass

def keyboardClick(button, interval = INTERVAL_CLICK):
    pydirectinput.keyDown(button)
    # delay(INTERVAL_KEYUP)
    pydirectinput.keyUp(button)
    delay(interval)

def keyboardClickRapid(button):
    pydirectinput.keyDown(button)
    # delay(0.008)
    pydirectinput.keyUp(button)
    delay(0.008)

def keyboardPress(button, interval = INTERVAL_CLICK):
    pydirectinput.keyDown(button)
    delay(interval)

def keyboardRelease(button, interval = INTERVAL_CLICK):
    pydirectinput.keyUp(button)
    delay(interval)

def inputAt():
    pydirectinput.keyDown("shift")
    delay(INTERVAL_CLICK)
    pydirectinput.keyDown("2")
    delay(INTERVAL_CLICK)
    pydirectinput.keyUp("2")
    delay(INTERVAL_CLICK)
    pydirectinput.keyUp("shift")
    delay(INTERVAL_CLICK)

def jump():
    keyboardClick("g")

def cleave():
    keyboardClick("f")
    delay(0.1)

def plummet():
    keyboardClick("y")

def left():
    keyboardClick("left")

def leftStep(interval = 0.1):
    keyboardPress("left")
    delay(interval)
    keyboardRelease("left")
    delay(INTERVAL_KEYUP)

def immediatelyLeft():
    pydirectinput.keyDown("left")
    pydirectinput.keyUp("left")
    delay(0.01)

def right():
    keyboardClick("right")

def rightStep(interval = 0.2):
    keyboardPress("right")
    delay(interval)
    keyboardRelease("right")
    delay(INTERVAL_KEYUP)

def fastJump():
    pydirectinput.keyDown("g")
    pydirectinput.keyDown("b")
    pydirectinput.keyUp("g")
    pydirectinput.keyUp("b")
    delay(INTERVAL_CLICK)

def doubleJump():
    keyboardClick("g")
    keyboardClick("g")

def tribleJump():
    keyboardClick("g")
    keyboardClick("g")
    keyboardClick("g")

def highJump():
    keyboardClick("g")
    keyboardPress("up")
    keyboardClick("g")
    keyboardRelease("up")

def doubleHighJump():
    keyboardPress("up")
    keyboardClickRapid("g")
    keyboardClickRapid("g")
    keyboardClickRapid("g")
    keyboardRelease("up")

def downJump():
    pydirectinput.keyDown("down")
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    pydirectinput.keyUp("down")

def groundAttack():
    cleave()
    delay(0.3)

def jumpAttack():
    jump()
    cleave()
    delay(0.2)

def flashJumpAttack():
    pydirectinput.keyDown("g")
    pydirectinput.keyDown("j")
    pydirectinput.keyDown("f")
    pydirectinput.keyUp("g")
    pydirectinput.keyUp("j")
    pydirectinput.keyUp("f")
    delay(0.2)

def flashJumpAttackHuntingDecree():
    pydirectinput.keyDown("g")
    pydirectinput.keyDown("j")
    pydirectinput.keyDown("f")
    pydirectinput.keyUp("g")
    pydirectinput.keyUp("j")
    pydirectinput.keyDown("e")
    pydirectinput.keyUp("f")
    pydirectinput.keyUp("e")
    delay(0.1)

def slowerFlashJumpAttack():
    pydirectinput.keyDown("g")
    delay(0.1)
    pydirectinput.keyDown("j")
    pydirectinput.keyDown("f")
    pydirectinput.keyUp("g")
    pydirectinput.keyUp("j")
    pydirectinput.keyUp("f")
    delay(0.15)

def highJumpAttack():
    highJump()
    cleave()
    delay(0.4)

def doubleHighJumpAttack():
    doubleHighJump()
    cleave()
    delay(0.5)

def doubleJumpAttack():
    doubleJump()
    cleave()
    delay(0.28)

def doubleJumpAttackHuntingDecree():
    doubleJump()
    cleave()
    delay(0.05)
    huntingDecree()

def tribleJumpAttack():
    tribleJump()
    cleave()
    delay(0.25)

def downJumpAttack():
    downJump()
    delay(0.1)
    cleave()

def huntingDecree():
    keyboardClick("e")
    delay(0.1)

def nobleSummons():
    keyboardClick("a")

def aetherBloom():
    keyboardClick("s")
    delay(0.5)

def impale():
    keyboardClick("h")
    delay(0.5)

def leftUpImpale():
    keyboardPress("up")
    delay(INTERVAL_KEYUP)
    keyboardPress("left")
    delay(INTERVAL_KEYUP)
    keyboardClick("h")
    delay(INTERVAL_KEYUP)
    keyboardRelease("left")
    delay(INTERVAL_KEYUP)
    keyboardRelease("up")
    delay(0.3)

def upImpale():
    keyboardPress("up")
    delay(INTERVAL_KEYUP)
    keyboardClick("h")
    delay(INTERVAL_KEYUP)
    keyboardRelease("up")
    delay(0.3)

def rush():
    keyboardClick("d")

def leftImpaleRush():
    pydirectinput.keyDown("left")
    pydirectinput.keyDown("h")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    delay(0.02)
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("left")

def rightImpaleRush():
    pydirectinput.keyDown("right")
    pydirectinput.keyDown("h")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    delay(0.02)
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("right")

def rightDownImpaleRush():
    pydirectinput.keyDown("right")
    pydirectinput.keyDown("down")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    delay(0.02)
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("down")
    pydirectinput.keyUp("right")

def leftUpImpaleRush():
    pydirectinput.keyDown("up")
    pydirectinput.keyDown("left")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("left")
    pydirectinput.keyUp("up")

def leftDownImpaleRush():
    pydirectinput.keyDown("down")
    pydirectinput.keyDown("left")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    delay(0.02)
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("left")
    pydirectinput.keyUp("down")

def jumpLeftUpImpaleRush():
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    leftUpImpaleRush()

def jumpRightDownImpaleRush():
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    rightDownImpaleRush()

def rightUpImpaleRush():
    pydirectinput.keyDown("up")
    pydirectinput.keyDown("right")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    delay(0.02)
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("right")
    pydirectinput.keyUp("up")

def upImpaleRush():
    pydirectinput.keyDown("up")
    pydirectinput.keyDown("h")
    pydirectinput.keyUp("h")
    delay(0.02)
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("up")

def sellAllEquips():
    keyboardClick("enter")
    delay(0.1)
    keyboardClick("/")
    keyboardClick("s")
    keyboardClick("enter")
    delay(0.1)
    inputAt()
    keyboardClick("s")
    keyboardClick("e")
    keyboardClick("l")
    keyboardClick("l")
    keyboardClick("enter")
    delay(0.2)
    keyboardClick("alt")
    delay(0.2)
    keyboardClick("alt")
    delay(0.2)
    keyboardClick("left")
    delay(0.2)
    keyboardClick("left")
    delay(0.2)
    keyboardClick("enter")
    delay(0.2)
    keyboardClick("alt")
    delay(0.4)

def totem():
    delay(0.2) # make sure the previous action was stoped (landing e.t.c.)
    keyboardClick("2")
    delay(0.6)

def buffSharpEyes():
    keyboardClick("3")
    delay(1)

def buffDsi():
    keyboardClick("4")
    delay(1)

def buffHs():
    keyboardClick("5")
    delay(1)

def sellRandomly(start, end):
    count = 0
    choosed = None
    between = range(start, end + 1)
    def choose():
        nonlocal choosed
        nonlocal count
        if choosed is None:
            choosed = random.choice(between)
            print("next sell at ", choosed)
        result = count % choosed == 0
        count = count + 1
        if result:
            choosed = None
            count = 1
        return result 
    return choose

def callWithInterval(func, intervalInSeconds):
    start = None
    def innerfunc():
        nonlocal start
        if start is None:
            start = time.time()
            func()
            return
        if time.time() - start >= intervalInSeconds:
            start = time.time()
            func()
            return
        return
    return innerfunc


def summonBall():
    pydirectinput.keyDown("down")
    pydirectinput.keyDown("n")
    pydirectinput.keyUp("n")
    pydirectinput.keyUp("down")
    delay(0.5)
ballCD = 60
summonBallWithInterval = callWithInterval(summonBall, ballCD)