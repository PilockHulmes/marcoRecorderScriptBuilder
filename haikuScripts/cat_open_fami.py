# (350, 400) (670, 400) (980, 400) 三个卡位置
# (683, 610) 确定

import pydirectinput
import time
from capture import Capture


capture = Capture("MapleStory")
capture.start()

time.sleep(2)

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

left = capture.window["left"]
top = capture.window["top"]

while running:
    time.sleep(1.5)
    pydirectinput.click(350 + left, 400 + top + 30)
    time.sleep(0.2)
    pydirectinput.click(670 + left, 400 + top + 30)
    time.sleep(0.2)
    pydirectinput.click(980 + left, 400 + top + 30)
    time.sleep(0.2)
    pydirectinput.click(683 + left, 610 + top + 30)