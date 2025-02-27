from catms.cube_washer import CubeWasher
import time

washer = CubeWasher()

time.sleep(3)

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

while running:
    time.sleep(1.5)
    bpot_lines = washer.readTextLineByLine()
    if washer.isLuckLines(bpot_lines):
        break
    washer.bpotAgain()