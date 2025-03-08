from catms.fami_washer import FamiWasher
import time

washer = FamiWasher()

time.sleep(3)

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

# TODO: 每次洗的时候记得切
FAMI_POS = (725,292) # 第一张

while running:
    time.sleep(0.3)
    fami_lines = washer.readTextLineByLine()
    if washer.isAttLines(fami_lines) or washer.isMattLines(fami_lines):
        break
    washer.wash(FAMI_POS)