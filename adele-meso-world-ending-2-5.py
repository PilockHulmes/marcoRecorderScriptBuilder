import commandBuilderLib as clib


WAIT_FALLING_EDGE = 1000


def init():
    return clib.join([
        clib.returnLeft(4),
        clib.jumpDown(),
        clib.jumpDown(),
        clib.jumpDown(),
    ])


def loopNormal():
    return clib.join([
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpRightLeftAttack(),
        clib.jumpHighLeft(),
        clib.flower(),
        clib.click("Left"),
        clib.jumpFarFront(),
        clib.slashDown(),  # 跳下边缘
        clib.click("Left"),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpLeftRightAttack(),
        clib.click("Right")
    ])


def loopSword():
    return clib.join([
        clib.jumpFront(),
        clib.summonSword(),
        clib.swordZone(),
        clib.jumpFront(),
        clib.summonSword(),
        clib.jumpFront(),
        clib.summonSword(),
        clib.jumpFront(),
        clib.jumpRightLeftAttack(),
        clib.jumpHighLeft(),
        clib.flower(),
        clib.click("Left"),
        clib.jumpFarFront(),
        clib.slashDown(),  # 跳下边缘
        clib.click("Left"),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpLeftRightAttack(),
        clib.click("Right")
    ])


def loopInfinity():
    return clib.join([
        clib.jumpFront(),
        clib.infinity(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpRightLeftAttack(),
        clib.jumpHighLeft(),
        clib.flower(),
        clib.click("Left"),
        clib.jumpFarFront(),
        clib.slashDown(),  # 跳下边缘
        clib.click("Left"),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpLeftRightAttack(),
        clib.click("Right")
    ])


def loopDestroy():
    return clib.join([
        clib.jumpFront(),
        clib.destroy(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpRightLeftAttack(),
        clib.jumpHighLeft(),
        clib.flower(),
        clib.click("Left"),
        clib.jumpFarFront(),
        clib.slashDown(),  # 跳下边缘
        clib.click("Left"),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpLeftRightAttack(),
        clib.click("Right")
    ])


def loopMagicBlast():
    return clib.join([
        clib.jumpFront(),
        clib.magicBlast(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpRightLeftAttack(),
        clib.jumpHighLeft(),
        clib.flower(),
        clib.click("Left"),
        clib.jumpFarFront(),
        clib.slashDown(),  # 跳下边缘
        clib.click("Left"),
        clib.jumpFront(),
        clib.jumpFront(),
        clib.jumpLeftRightAttack(),
        clib.click("Right")
    ])


combination = [
    clib.wait(500),
    init(),
    clib.click("Right"),
]

for i in range(10):
    combination.append(clib.start())
    loop1 = clib.join([
        loopSword(),
        loopInfinity(),
        loopDestroy(),
        loopMagicBlast(),
    ])
    loop2 = clib.join([
        loopSword(),
        loopNormal(),
        loopNormal(),
        loopNormal(),
    ])
    loop3 = clib.join([
        loopSword(),
        loopNormal(),
        loopDestroy(),
        loopMagicBlast(),
    ])
    loop4 = clib.join([
        loopSword(),
        loopNormal(),
        loopNormal(),
        loopNormal(),
    ])
    combination.append(loop1)
    combination.append(loop2)
    combination.append(loop3)
    combination.append(loop4)


with open("adele-meso-world-ending.mcr", "w", encoding="utf-8") as file:
    file.write(clib.join(combination))
