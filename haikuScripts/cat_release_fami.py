import pydirectinput
import time
from capture import Capture

from pynput import keyboard
running = True
stop_key = "l"
def stopWhenPress(pressed_key):
    global running
    try:
        if pressed_key.char == stop_key:
            running = False
            return False
    except AttributeError:
        pass
listener = keyboard.Listener(on_press=stopWhenPress)
listener.start()

capture = Capture("MapleStory")
capture.start()

time.sleep(2)

# (848, 382) 第二张 fami 卡的位置
# (555, 617) 放生按钮位置
left = capture.window["left"]
top = capture.window["top"]
while running:
    time.sleep(0.2)
    pydirectinput.rightClick(781 + left, 297 + top + 30)
    time.sleep(0.2) 
    pydirectinput.click(488 + left, 529 + top + 30) # 第一次点击是点掉右键菜单
    time.sleep(0.2)
    pydirectinput.click(488 + left, 529 + top + 30)
    if not running:
        break
    time.sleep(0.2)
    pydirectinput.press("enter")