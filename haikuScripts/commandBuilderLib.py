import pyautogui
import pydirectinput
import time

LINE_DELIMITER = "\n"
INTERVAL_CLICK = 0.05
INTERVAL_JUMP = 0.06
INTERVAL_DOUBLE_JUMP_LANDING = 550 / 1000  # 同层跳跃落地间隔
INTERVAL_SLASH = 220 / 1000  # 穿刺动作长度
INTERVAL_SLASH_END = 600 / 1000  # 魔剑共鸣动作长度

def keyboardClick(button, interval = INTERVAL_CLICK):
    pydirectinput.keyDown(button)
    time.sleep(interval)
    pydirectinput.keyUp(button)
    time.sleep(interval)

def inputAt():
    pydirectinput.keyDown("shift")
    time.sleep(INTERVAL_CLICK)
    pydirectinput.keyDown("2")
    time.sleep(INTERVAL_CLICK)
    pydirectinput.keyUp("2")
    time.sleep(INTERVAL_CLICK)
    pydirectinput.keyUp("shift")
    time.sleep(INTERVAL_CLICK)

def jump():
    keyboardClick("g")

def slash():
    keyboardClick("f", 0.06)

def left():
    keyboardClick("left")

def right():
    keyboardClick("right")

def doubleJump():
    keyboardClick("g", 0.04)
    keyboardClick("g", 0.04)

def jumpAttack():
    doubleJump()
    slash()
    time.sleep(0.35)

def sellAllEquips():
    keyboardClick("enter")
    time.sleep(0.1)
    inputAt()
    keyboardClick("s")
    keyboardClick("e")
    keyboardClick("l")
    keyboardClick("l")
    keyboardClick("enter")
    time.sleep(0.2)
    keyboardClick("alt")
    time.sleep(0.2)
    keyboardClick("alt")
    time.sleep(0.2)
    keyboardClick("left")
    time.sleep(0.2)
    keyboardClick("left")
    time.sleep(0.2)
    keyboardClick("enter")
    time.sleep(0.2)
    keyboardClick("alt")