import commandBuilderLib as lib
import time
import pydirectinput
from pynput import keyboard

time.sleep(3)

running = True

def on_press(key):
    global running
    try:
        if key.char == 'l':
            running = False
            return False  # 停止监听器
    except AttributeError:
        pass

listener = keyboard.Listener(on_press=on_press)
listener.start()

while running:
    time.sleep(0.3)
    if not running:
        break
    pydirectinput.doubleClick()
    if not running:
        break
    time.sleep(0.3)
    if not running:
        break
    pydirectinput.click()
    if not running:
        break
    time.sleep(0.2)
    if not running:
        break
    lib.keyboardClick("enter")
    if not running:
        break
    time.sleep(0.2)
    if not running:
        break
    lib.keyboardClick("tab")
    if not running:
        break

listener.stop()