import commandBuilderLib as clib

combination = [
    clib.wait(500),
    clib.returnLeft(3),
    clib.wait(600),
    clib.rightClick(),
]

commonLoopSecondHalf = clib.join([
    clib.slashUp(),
    clib.recall(),
    clib.rightClick(),
    clib.jumpFarFarRight(),
    clib.jumpFarFarRight(),
    clib.flower(),
    clib.leftClick(),
    clib.baseAttack(),
    clib.rightClick(),
    clib.jumpFront(),
    clib.jumpRightLeftAttack(),
    clib.wait(300)
])