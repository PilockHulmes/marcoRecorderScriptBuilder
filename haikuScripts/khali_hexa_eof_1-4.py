from khali import commands as lib
from returnToPoint import Return
import time
from khali.common_used_funcs import *

# Position 0 is (0.2158273381294964, 0.5035971223021583)
# Position 1 is (0.5467625899280576, 0.4316546762589928)
# Position 2 is (0.8848920863309353, 0.38848920863309355)
# Position 3 is (0.7841726618705036, 0.5035971223021583)
# Position 4 is (0.8201438848920863, 0.5035971223021583)
# Position 5 is (0.8489208633093526, 0.38848920863309355)

JANUS_POSITION = (0.2158273381294964, 0.5035971223021583) # also left jump threshold
JANUS_POSITION_HIGHER = (0.35251798561151076, 0.4316546762589928)
PLAYER_POSITION = (0.5467625899280576, 0.4316546762589928)
RIGHT_JUMP_THRESHOLD = (0.7841726618705036, 0.5035971223021583)
RIGHT_STAIR_GROUND = (0.8201438848920863, 0.5035971223021583)
FOUNTAIN_POSITION = (0.8705035971223022, 0.38848920863309355)

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

    r.returnToPoint(PLAYER_POSITION)
    if lib.skillOnCooldown(lib.last_use_fountain - 20, 60):
        time.sleep(0.3)
        lib.blossom()
        leftBackwardRing()
        time.sleep(LANDING_INTEVAL)
        r.returnToPoint(JANUS_POSITION_HIGHER)
        lib.slash()
        time.sleep(0.4)
        lib.janus()
        time.sleep(0.1)
        leftBackwardRing()
        time.sleep(0.8) # jump out of platform
        # if config.player_position[0] < JANUS_POSITION[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
        #     leftBackwardRing()
        #     time.sleep(LANDING_INTEVAL)
        # if config.player_position[0] < JANUS_POSITION[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
        #     leftBackwardRing()g
        #     time.sleep(LANDING_INTEVAL)
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        r.returnToPoint(JANUS_POSITION)
        lib.slash()
        time.sleep(0.4)
        lib.janus()
        time.sleep(0.1)
        oblivion()
        rightForwardRing()
        time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < FOUNTAIN_POSITION[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        if config.player_position[0] < FOUNTAIN_POSITION[0] and config.player_position[0] != 0 and config.player_position[1] != 0:
            rightBackwardRing()
            time.sleep(LANDING_INTEVAL)
        lib.hold("right", 0.4)
        lib.upJumpSlash("left")
        time.sleep(0.4)
        r.returnToPoint(FOUNTAIN_POSITION)
        lib.slash()
        time.sleep(0.4)
        lib.fountain()
        leftTripleForwardRing()
        time.sleep(0.8) # jump out of platform
        r.returnToPoint(PLAYER_POSITION)
        lib.slash()
        time.sleep(0.4)
    else:
        r.returnToPoint(PLAYER_POSITION)
        lib.slash()
        time.sleep(0.4)
        always_oblivion()
        lib.click("left")
        lib.ring()
        time.sleep(0.2)
        lib.click("right")
        lib.slash()
        time.sleep(0.4)
        lib.fury()
        time.sleep(0.2)
        lib.slash()
        time.sleep(0.4)