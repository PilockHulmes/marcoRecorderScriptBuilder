from khali import commands as lib
from returnToPoint import Return
import time

rune_text = "精英首领的诅咒应用中"

r = Return(window_name="MapleStory", rune_text = "的诅咒应用中")
r.start()
time.sleep(1)
r.save()

totem = lib.callWithInterval(lib.buffFactory("f9"), 360) # 6min totem
holy_symbol = lib.callWithInterval(lib.buffFactory("f5"), 1200) # 20min buff
eagle_eye = lib.callWithInterval(lib.buffFactory("f8"), 1200) # 20min buff
loot_loop = lib.returnTrueWithInterval(120) # every 2 min is loot loop

while lib.running:
    totem()
    holy_symbol()
    eagle_eye()

    if loot_loop():
        for i in range(5):
            lib.doubleJumpSlash("right")
            time.sleep(0.2)

        lib.upJumpSlash("left")
        time.sleep(0.3)
        for i in range(2):
            lib.tripleJumpSlash("left")
            time.sleep(0.2)
        for i in range(2):
            lib.doubleJumpSlash("left")
            time.sleep(0.2)
        time.sleep(0.2) # extra landing since cross platform
    else:
        lib.doubleJumpDash(6, "right")
        time.sleep(0.1)
        lib.click("space") # somehow the reset cooldown not done yet, need reset again
        time.sleep(0.3)
        lib.upJumpDash(6, "left")
        time.sleep(0.1)
        lib.click("space") # somehow the reset cooldown not done yet, need reset again
        time.sleep(0.3) # wait for animation
        r.returnToSavePoint()
        # time.sleep(0.1) # no need to sleep if use return to save point