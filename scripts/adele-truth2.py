
import commandBuilderLib as clib

combination = [
    clib.wait(500),
    clib.returnRight(5),
    clib.wait(600),
    clib.leftClick(),
]

commonLoopSecondHalf = clib.join([
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFarFarRight(),
    clib.jumpFarFarRight(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
])

shardLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.shard(),
    clib.jumpFront(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

shardSummonLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.shard(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

zoneLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.swordZone(),
    clib.jumpFront(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

zoneSummonLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.swordZone(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

infinityLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.infinity(),
    clib.jumpFront(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

infinitySummonLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.infinity(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

destroyLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.destroy(),
    clib.jumpFront(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

destroySummonLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.destroy(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

magicBlastLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.magicBlast(),
    clib.jumpFront(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

magicBlastSummonLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.magicBlast(),
    clib.jumpFront(),
    clib.summonSword(),
    clib.jumpFront(),
    commonLoopSecondHalf
])

print("infinityLoop:        ", clib.countDuration(infinityLoop))
print("infinitySummonLoop:  ", clib.countDuration(infinitySummonLoop))
print("zoneLoop:            ", clib.countDuration(zoneLoop))
print("zoneSummonLoop:      ", clib.countDuration(zoneSummonLoop))
print("destroyLoop:         ", clib.countDuration(destroyLoop))
print("destroySummonLoop:   ", clib.countDuration(destroySummonLoop))
print("magicBlastLoop:      ", clib.countDuration(magicBlastLoop))
print("magicBlastSummonLoop:", clib.countDuration(magicBlastSummonLoop))
print("shardLoop:           ", clib.countDuration(shardLoop))
print("shardSummonLoop:     ", clib.countDuration(shardSummonLoop))

combination.append(
    clib.forLoop(
        20,
        clib.join([
            clib.start(),
            clib.forLoop(
                2,
                clib.join([
                    infinitySummonLoop, zoneLoop, destroyLoop, magicBlastLoop,
                    zoneSummonLoop, shardLoop, shardLoop, zoneLoop,
                    destroySummonLoop, magicBlastLoop, zoneLoop, shardLoop,
                    shardSummonLoop, zoneLoop, destroySummonLoop, magicBlastLoop,
                    zoneSummonLoop, shardLoop
                ])
            )
        ])
    )
)

with open("adele-truth2.mcr", "w", encoding="utf-8") as file:
    file.write(clib.join(combination))
