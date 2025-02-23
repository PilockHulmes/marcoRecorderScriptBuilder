from khali import commands as lib
from returnToPoint import Return
import time
from functools import partial
import config

# 左侧楼梯地面 (0.10179640718562874, 0.28143712574850294)
# 左侧楼梯台阶 (0.10179640718562874, 0.17964071856287425)
# 阈值 is (0.8862275449101796, 0.28143712574850294)
# 右侧楼梯地面 is (0.9281437125748503, 0.28143712574850294)
# 右侧楼梯台阶 is (0.9281437125748503, 0.19161676646706585)
# 一人宽的距离 in 0 (0.0658682634730539, 0.10179640718562874) in 1 (0.07784431137724551, 0.10179640718562874)
CHARACTER_WIDTH = 0.07784431137724551 - 0.0658682634730539
JUMP_ATTACK_THRESHOLD = (0.8203592814371258, 0.28143712574850294)
LEFT_STAIR_GROUND = (0.10179640718562874, 0.28143712574850294)
LEFT_STAIR_PLATFORM = (0.10179640718562874, 0.17964071856287425)
RIGHT_STAIR_GROUND = (0.9281437125748503, 0.28143712574850294)
RIGHT_STAIR_PLATFORM = (0.9281437125748503, 0.19161676646706585)

rune_text = "精英首领的诅咒应用中"

r = Return(window_name="MapleStory", rune_text = "的诅咒应用中", ocr_lang="ch", ignore_rune_text_seconds=60)
r.start()
time.sleep(1)
r.save()

totem = lib.callWithInterval(lib.buffFactory("f9", 1), 360) # 6min totem
guild_boss = lib.callWithInterval(lib.buffFactory("f5"), 1200) # 20min buff
guild_ied = lib.callWithInterval(lib.buffFactory("f6"), 1200) # 20min buff
guild_dmg = lib.callWithInterval(lib.buffFactory("f7"), 1200) # 20min buff
guild_cd = lib.callWithInterval(lib.buffFactory("f8"), 1200) # 20min buff
oblivion = lib.callWithInterval(lib.buffFactory("a"), 115)
loot_loop = lib.returnTrueWithInterval(60) # every 2 min item despwan
flower_loop = lib.callWithInterval(lib.flowering, 56)


rightForwardRing = lib.rotateWithInterval(partial(lib.doubleJumpForwardRing, "right"), lib.doubleJumpSlash, 4)
rightBackwardRing = lib.rotateWithInterval(partial(lib.doubleJumpBackwardRing, "right"), partial(lib.doubleJumpBackwardSlash, "right"), 4)
leftForwardRing = lib.rotateWithInterval(partial(lib.doubleJumpForwardRing, "left"), lib.doubleJumpSlash, 4)
leftBackwardRing = lib.rotateWithInterval(partial(lib.doubleJumpBackwardRing, "left"), partial(lib.doubleJumpBackwardSlash, "left"), 4)

def withinHorizontalThreshold(target_position, threshold):
    return abs(target_position[0] - config.player_position[0]) <= threshold

def withinVerticalThreshold(target_postion, threshold):
    return abs(target_postion[1] - config.player_position[1]) <= threshold 

LANDING_INTEVAL = 0.34

while lib.running:
    totem()
    guild_dmg()
    guild_cd()
    oblivion()
    # holy_symbol()
    # eagle_eye()

    if config.player_position[0] < LEFT_STAIR_GROUND[0]:
        lib.click("right")
        lib.click("right")
        lib.doubleJumpSlash()
        time.sleep(LANDING_INTEVAL)
    if loot_loop():
    # if True:

        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < RIGHT_STAIR_GROUND[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightForwardRing()
            time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < RIGHT_STAIR_GROUND[0] and config.player_position[0] != 0 and config.player_position[1] != 0: 
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < RIGHT_STAIR_GROUND[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < RIGHT_STAIR_GROUND[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        oblivion()
        if withinHorizontalThreshold(RIGHT_STAIR_GROUND,CHARACTER_WIDTH * 2):
            if config.player_position[0] <= RIGHT_STAIR_GROUND[0]:
                lib.hold("left", 0.3)
            else:
                lib.hold("right", 0.3)
        lib.upJumpSlash("left")
        time.sleep(0.4)
        if config.player_position[1] > RIGHT_STAIR_PLATFORM[1]:
            lib.upJumpSlash("left")
            time.sleep(0.4)
        lib.tripleJumpSlash()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[1] > RIGHT_STAIR_PLATFORM[1]:
            lib.upJumpSlash("left")
            time.sleep(0.4)
        lib.tripleJumpSlash()
        time.sleep(LANDING_INTEVAL)
        leftBackwardRing()
        time.sleep(LANDING_INTEVAL)
        leftBackwardRing()
        time.sleep(LANDING_INTEVAL) # extra landing since cross platform
    else:
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        flower_loop()
        if config.player_position[0] < JUMP_ATTACK_THRESHOLD[0] and config.player_position[0] != 0 and config.player_position[1] != 0:        
            rightForwardRing()
            time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < JUMP_ATTACK_THRESHOLD[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < JUMP_ATTACK_THRESHOLD[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        oblivion()
        if withinHorizontalThreshold(RIGHT_STAIR_GROUND,CHARACTER_WIDTH * 2):
            if config.player_position[0] <= RIGHT_STAIR_GROUND[0]:
                lib.hold("left", 0.3)
            else:
                lib.hold("right", 0.3)
        lib.upJumpDash(6, "left")
        time.sleep(0.6) # wait for landing
    # need down jump if on the 2nd platform
    if withinVerticalThreshold(LEFT_STAIR_PLATFORM, CHARACTER_WIDTH):
        if withinHorizontalThreshold(LEFT_STAIR_PLATFORM,CHARACTER_WIDTH):
            if config.player_position[0] <= LEFT_STAIR_GROUND[0]:
                lib.hold("left", 0.2)
            else:
                lib.hold("right", 0.2)
            lib.downJump()
            time.sleep(0.4)
        else:
            lib.downJump()
            time.sleep(0.4)