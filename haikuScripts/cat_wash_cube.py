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
    # if washer.isLuckTwoLines250(bpot_lines) or washer.isXenoThreeLines250(bpot_lines):
    # if washer.is2LCdr(bpot_lines) or washer.is1LineCDR2LineLuk250(bpot_lines):
    # if washer.isThreeLineAttack(bpot_lines):
    # if washer.isLuckThreeLines250(bpot_lines) or washer.isXenoThreeLines250(bpot_lines):
    if washer.isLuckThreeLines(bpot_lines) or washer.isSellableThreeLines(bpot_lines):
    # if washer.isLuckTwoLines(bpot_lines) or washer.isAnyThreeLines(bpot_lines):
        break
    if not running:
        break
    washer.bpotAgain()