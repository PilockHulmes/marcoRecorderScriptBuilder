import time
from returnToPoint import Return
import pydirectinput

time.sleep(3)

r = Return()
r.start()

time.sleep(1)

r.save()

# test return to save point
while True:
    time.sleep(1)
    print("you have 3 seconds to go freely")
    print("3")
    time.sleep(1)
    print("2")
    time.sleep(1)
    print("1")
    time.sleep(1)
    print("0")
    time.sleep(1)
    r.returnToSavePoint()


# # test walking speed with 150
# time.sleep(1)
# pydirectinput.keyDown("left")
# time.sleep(3)
# pydirectinput.keyUp("left")
# r.calculateDistance()