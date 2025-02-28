from catms.cube_washer import CubeWasher
import time



washer = CubeWasher()

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

while running:
    time.sleep(1.5)
    bpot_lines = washer.readTextLineByLine()
    if washer.isSellableThreeLines(bpot_lines) or washer.isLuckTwoLines(bpot_lines):
        break
    washer.bpotAgain()