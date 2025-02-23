from khali import commands as lib
from returnToPoint import Return
import time
from khali.common_used_funcs import *

rune_text = "精英首领的诅咒应用中"


CHARACTER_WIDTH = 0.07784431137724551 - 0.0658682634730539
JUMP_ATTACK_THRESHOLD = (0.7756410256410257, 0.3333333333333333)
LEFT_STAIR_GROUND = (0.19230769230769232, 0.3333333333333333)
LEFT_STAIR_PLATFORM = (0.1987179487179487, 0.23076923076923075)
RIGHT_STAIR_GROUND = (0.8589743589743589, 0.3333333333333333)
RIGHT_STAIR_PLATFORM = (0.8589743589743589, 0.23076923076923075)

r = Return(window_name="MapleStory", rune_text = "的诅咒应用中", ocr_lang="ch", ignore_rune_text_seconds=60)
r.start()
time.sleep(1)
r.save()

LANDING_INTEVAL = 0.34

while lib.running:
    totem()
    guild_dmg()
    guild_cd()
    oblivion()

    if config.player_position[0] < LEFT_STAIR_GROUND[0]:
        lib.click("right")
        lib.click("right")
        rightForwardRing()
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
        lib.doubleJumpSlash()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[1] > RIGHT_STAIR_PLATFORM[1]:
            lib.upJumpSlash("left")
            time.sleep(0.4)
        lib.doubleJumpSlash()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[1] > RIGHT_STAIR_PLATFORM[1]:
            lib.upJumpSlash("left")
            time.sleep(0.4)
        leftBackwardRing()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[1] > RIGHT_STAIR_PLATFORM[1]:
            lib.upJumpSlash("left")
            time.sleep(0.4)
        leftBackwardRing()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[0] >= RIGHT_STAIR_GROUND[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            leftBackwardRing()
            time.sleep(LANDING_INTEVAL) # extra landing since cross platform
        time.sleep(0.6) # wait for landing
    else:
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        flower_loop()
        if config.player_position[0] < RIGHT_STAIR_GROUND[0] and config.player_position[0] != 0 and config.player_position[1] != 0:        
            rightForwardRing()
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