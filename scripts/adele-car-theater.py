import commandBuilderLib as clib

combination = [
    clib.wait(500),
]

jumpBack = clib.join([
    clib.returnRight(4),
    clib.wait(300),
    clib.leftClick(),
    clib.jumpFront(),
    clib.slashLeftUp()
])


baseLoop = clib.join([
    clib.jumpFarFarLeft(),
    clib.baseAttack(),
    clib.jumpFarFarRight(),
    clib.baseAttack(),
])

tenSecondsLoop = clib.join([
    baseLoop,
    baseLoop,
    baseLoop,
    clib.jumpFarFarLeft(),
    clib.baseAttack(),
    clib.recall(),
    clib.jumpFarFarRight(),
    clib.baseAttack(),
    clib.flower(),
])

reset = clib.join([
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.leftClick(),
    clib.jumpFront(),
    clib.slashLeftUp()
])

tenSecondsSummonLoop = clib.join([
    baseLoop,
    clib.summonSword(),
    baseLoop,
    clib.summonSword(),
    baseLoop,
    clib.summonSword(),
    clib.jumpFarFarLeft(),
    clib.baseAttack(),
    clib.recall(),
    clib.wait(clib.INTERVAL_CLICK),
    clib.jumpFarFarRight(),
    clib.baseAttack(),
    clib.flower(),
])


routine = clib.join([
    jumpBack,
    clib.start(),
    clib.forLoop(2, clib.join([
        clib.infinity(),
        tenSecondsSummonLoop,
        clib.swordZone(),
        tenSecondsLoop,
        clib.magicBlast(),
        tenSecondsLoop,
        clib.destroy(),
        tenSecondsLoop,
        clib.swordZone(),
        reset,
        tenSecondsSummonLoop,
        tenSecondsLoop,
        tenSecondsLoop,
        clib.swordZone(),
        tenSecondsLoop,
        clib.magicBlast(),
        reset,
        tenSecondsSummonLoop,
        clib.destroy(),
        tenSecondsLoop,
        clib.swordZone(),
        tenSecondsLoop,
        tenSecondsLoop,
        reset,
        tenSecondsSummonLoop,
        clib.swordZone(),
        tenSecondsLoop,
        clib.magicBlast(),
        tenSecondsLoop,
        clib.destroy(),
        tenSecondsLoop,
        clib.swordZone(),
        reset,
        tenSecondsSummonLoop,
        tenSecondsLoop,
    ]))
])


print("baseLoop:", clib.countDuration(baseLoop))

combination.append(clib.forLoop(20, routine))

with open("adele-car-theater.mcr", "w", encoding="utf-8") as file:
    file.write(clib.join(combination))
