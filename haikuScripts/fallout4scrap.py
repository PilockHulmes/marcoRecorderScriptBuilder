import time
import commandBuilderLib as lib
import time
from returnToPoint import Return
import pydirectinput

time.sleep(6)

while True:
    pydirectinput.keyDown("r")
    pydirectinput.keyUp("r")
    time.sleep(0.05)
    pydirectinput.keyDown("enter")
    pydirectinput.keyUp("enter")
    time.sleep(0.05)