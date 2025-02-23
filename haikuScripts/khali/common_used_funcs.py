import khali.commands as lib
import config
from functools import partial
import returnToPoint

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

standStillRotate = lib.multiRotateWithInterval(
    [
        (partial(lib.ring, True), 3.5),
        (partial(lib.fury, True), 3.5),
        (partial(lib.jumpSlash, "left", True), 0)
    ]
)
