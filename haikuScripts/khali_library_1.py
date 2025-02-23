from khali import commands as lib
from returnToPoint import Return
import time

rune_text = "精英首领的诅咒应用中"


r = Return(window_name="MapleStory", rune_text = "的诅咒应用中", ocr_lang="ch", ignore_rune_text_seconds=60)
r.start()
time.sleep(1)
r.save()

totem = lib.callWithInterval(lib.buffFactory("f9"), 360) # 6min totem
holy_symbol = lib.callWithInterval(lib.buffFactory("f5"), 1200) # 20min buff
eagle_eye = lib.callWithInterval(lib.buffFactory("f8"), 1200) # 20min buff
loot_loop = lib.returnTrueWithInterval(60) # every 2 min item despwan
flower_loop = lib.callWithInterval(lib.flowering, 56)

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
            # lib.slash()
        time.sleep(0.2)
        for i in range(2):
            lib.doubleJumpSlash("left")
            time.sleep(0.3)
        time.sleep(0.2) # extra landing since cross platform
    else:
        for i in range(2):
            lib.doubleJumpSlash("right")
            time.sleep(0.2)
        flower_loop()
        for i in range(2):
            lib.doubleJumpSlash("right")
            time.sleep(0.2)
        lib.upJumpDash(6, "left")
        time.sleep(0.1)
        lib.click("space") # somehow the reset cooldown not done yet, need reset again
        time.sleep(0.1) #landing