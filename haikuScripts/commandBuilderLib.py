import pyautogui
import pydirectinput
import time

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

def left():
    keyboardClick("left")

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
    keyboardPress("down")
    keyboardClickRapid("g")
    keyboardRelease("down")

def groundAttack():
    cleave()
    delay(0.3)

def jumpAttack():
    jump()
    cleave()
    delay(0.2)

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

def sellAllEquips():
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
    delay(0.3)

def totem():
    keyboardClick("6")
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