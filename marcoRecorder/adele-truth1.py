import commandBuilderLib as clib


combination = [
    clib.wait(500),
    clib.returnRight(5),
    clib.wait(600),
    clib.leftClick(),
]


def buildSummonLoop(action):
    return clib.join([
        clib.jumpFarFarLeft(),
        clib.summonSword(),
        action(),
        clib.jumpFarFarLeft(),
        clib.summonSword(),
        clib.jumpFarFarLeft(),
        clib.summonSword(),
        clib.jumpHighRight(),
        clib.recall(),
        clib.rightClick(),
        clib.jumpFarFarRight(),
        clib.baseAttack(),
        clib.jumpFarFarRight(),
        clib.flower(),
        clib.jumpFarFarRight(),
        clib.jumpRightLeftAttack(),
        clib.wait(300),
        clib.leftClick()
    ])


def buildNormalLoop(action):
    return clib.join([
        clib.jumpFarFarLeft(),
        action(),
        clib.jumpFarFarLeft(),
        clib.jumpFarFarLeft(),
        clib.jumpHighRight(),
        clib.recall(),
        clib.rightClick(),
        clib.jumpFarFarRight(),
        clib.baseAttack(),
        clib.jumpFarFarRight(),
        clib.flower(),
        clib.jumpFarFarRight(),
        clib.jumpRightLeftAttack(),
        clib.wait(300),
        clib.leftClick()
    ])


shardLoop = buildNormalLoop(clib.shard)

shardSummonLoop = buildSummonLoop(clib.shard)

zoneLoop = buildNormalLoop(clib.swordZone)

zoneSummonLoop = buildSummonLoop(clib.swordZone)

infinityLoop = buildNormalLoop(clib.infinity)

infinitySummonLoop = buildSummonLoop(clib.infinity)

destroyLoop = buildNormalLoop(clib.destroy)

destroySummonLoop = buildSummonLoop(clib.destroy)

magicBlastLoop = buildNormalLoop(clib.magicBlast)

magicBlastSummonLoop = buildSummonLoop(clib.magicBlast)

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

with open("adele-truth1.mcr", "w", encoding="utf-8") as file:
    file.write(clib.join(combination))
