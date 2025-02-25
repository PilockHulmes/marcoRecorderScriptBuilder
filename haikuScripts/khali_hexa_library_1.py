from khali import commands as lib
from returnToPoint import Return
import time
from khali.common_used_funcs import *

CHARACTER_WIDTH = 0.07784431137724551 - 0.0658682634730539
JUMP_ATTACK_THRESHOLD = (0.7756410256410257, 0.3333333333333333)
LEFT_STAIR_GROUND = (0.19230769230769232, 0.3333333333333333)
LEFT_STAIR_PLATFORM = (0.1987179487179487, 0.23076923076923075)
RIGHT_STAIR_GROUND = (0.8589743589743589, 0.3333333333333333)
RIGHT_STAIR_PLATFORM = (0.8589743589743589, 0.23076923076923075)

# Position 0 is (0.8076923076923077, 0.23076923076923075)
# Position 1 is (0.532051282051282, 0.23076923076923075)
# Position 2 is (0.26282051282051283, 0.23076923076923075)

JANUS_POSITION = (0.8076923076923077, 0.23076923076923075)
FOUNTAIN_POSITION = (0.532051282051282, 0.23076923076923075)
STAND_STILL_POSITION = (0.26282051282051283, 0.23076923076923075)

r = Return(window_name="MapleStory", rune_text = "的诅咒应用中", ocr_lang="ch", ignore_rune_text_seconds=60)
r.start()
time.sleep(1)

LANDING_INTEVAL = 0.34


always_oblivion = lib.buffFactory("a")

while lib.running:
    totem()
    guild_dmg()
    guild_cd()
    oblivion()

    r.returnToPoint(STAND_STILL_POSITION)
    if lib.skillOnCooldown(lib.last_use_fountain - 8, 60):
        time.sleep(0.3)
        leftBackwardRing()
        time.sleep(0.6)
        if withinVerticalThreshold(LEFT_STAIR_PLATFORM, CHARACTER_WIDTH):
            lib.downJump()
            time.sleep(0.4)
        oblivion()
        lib.click("right")
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
        r.returnToPoint(JANUS_POSITION)
        lib.janus()
        lib.tripleJumpSlash("left")
        time.sleep(LANDING_INTEVAL)
        r.returnToPoint(FOUNTAIN_POSITION)
        lib.fountain()
        lib.tripleJumpSlash("left")
        time.sleep(LANDING_INTEVAL)
        r.returnToPoint(STAND_STILL_POSITION)
    else:
        r.returnToPoint(STAND_STILL_POSITION)
        always_oblivion()
        lib.click("left")
        lib.ring()
        time.sleep(0.2)
        lib.slash()
        time.sleep(0.4)
        lib.fury()
        lib.click("left")
        time.sleep(0.2)
        lib.slash()
        # print("first rotate")
        # standStillRotate()
        # print("second rotatte")
        # standStillRotate()
        # print("third rotate")
        # standStillRotate()