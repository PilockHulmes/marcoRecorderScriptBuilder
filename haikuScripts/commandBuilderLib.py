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

def jump():
    keyboardClick("g")

def slash():
    keyboardClick("f", 0.06)

def left():
    keyboardClick("left")

def right():
    keyboardClick("right")

def doubleJump():
    keyboardClick("g", 0.05)
    keyboardClick("g", 0.05)

def jumpAttack():
    doubleJump()
    slash()
    time.sleep(0.4)