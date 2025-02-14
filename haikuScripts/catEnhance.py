import commandBuilderLib as lib
import time
import pydirectinput

time.sleep(3)

while True:
    time.sleep(0.3)
    pydirectinput.doubleClick()
    time.sleep(0.3)
    pydirectinput.click()
    time.sleep(0.2)
    lib.keyboardClick("enter")
    time.sleep(0.2)
    lib.keyboardClick("tab")
