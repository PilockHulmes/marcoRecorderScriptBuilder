
import commandBuilderLib as clib

combination = [
    clib.wait(500),
    clib.returnRight(5),
    clib.wait(600),
    clib.leftClick(),
]

shardLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.shard(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
])

shardSummonLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.shard(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
])

zoneLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.swordZone(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
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
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
])

infinityLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.infinity(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
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
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
])

destroyLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.destroy(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
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
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
])

magicBlastLoop = clib.join([
    clib.leftClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.magicBlast(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
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
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.flower(),
    clib.jumpFront(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(600)
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
