import pydirectinput
import time
from capture import Capture
# (705, 70) 消耗左上角奥
# (30, 30) 一格子长宽
# 10 格子之间的距离
# 16 横格子数量
# 8 竖格子数量


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

INIT_CELL = (705, 70 + 30)
WIDTH = 42
HEIGHT = 42
WIDTH_CELLS = 16
HEIGHT_CELLS = 8

TOTAL_COUNT = WIDTH_CELLS * HEIGHT_CELLS - 1 # 最后的是拍卖券
capture = Capture("MapleStory")
capture.start()

time.sleep(3)

current_point = INIT_CELL
width_pos = 0
height_pos = 0
for i in range(TOTAL_COUNT):
    if not running:
        break
    if width_pos % WIDTH_CELLS == 0 and width_pos != 0:
        width_pos = 0
        height_pos += 1
    pydirectinput.doubleClick(
        INIT_CELL[0] + capture.window["left"] + width_pos * WIDTH,
        INIT_CELL[1] + capture.window["top"] + height_pos * HEIGHT
    )
    width_pos += 1
    time.sleep(0.2)