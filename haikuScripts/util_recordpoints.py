from returnToPoint import Return
import time
from pynput import keyboard
import config
import sys

r = Return(window_name="MapleStory")
r.start()
time.sleep(1)
print("Initialized")

running = True
mapping_numbers = [str(i) for i in range(10)]
print(mapping_numbers)
stored_points = {}
def stopWhenPress(pressed_key):
    global running
    try:
        if pressed_key.char == "L".lower():
            running = False
            return False
        if pressed_key.char in mapping_numbers:
            time.sleep(0.1)
            stored_points[pressed_key.char] = config.player_position
            print(f"Saved position in {pressed_key.char}", config.player_position)
    except AttributeError:
        pass

listener = keyboard.Listener(on_press=stopWhenPress)
listener.start()


while running:
    try:
        time.sleep(30)
    except KeyboardInterrupt:
        for i in range(10):
            if str(i) in stored_points:
                print(f"Position {i} is {stored_points[str(i)]}")
        sys.exit(0)