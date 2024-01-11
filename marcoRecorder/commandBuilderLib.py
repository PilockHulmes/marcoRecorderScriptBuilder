import re

LINE_DELIMITER = "\n"
INTERVAL_CLICK = 70
INTERVAL_JUMP = 70
INTERVAL_DOUBLE_JUMP_LANDING = 550  # 同层跳跃落地间隔
INTERVAL_SLASH = 220  # 穿刺动作长度
INTERVAL_SLASH_END = 600  # 魔剑共鸣动作长度

PATTERN_DELAY = "DELAY : ([0-9]+)\n"


def countDuration(command):
    result = re.findall(PATTERN_DELAY, command)
    count = 0
    for delay in result:
        count += int(delay)
    return count


def forLoop(times, commandStr):
    return join([
        f"REPEAT : {times} : 0 : 0 : Enter the number of iterations: : 0 : 0",
        commandStr,
        "ENDREPEAT",
    ])


def join(commands):
    return LINE_DELIMITER.join(commands)


def keyDown(key):
    return f"Keyboard : {key} : KeyDown"


def keyUp(key):
    return f"Keyboard : {key} : KeyUp"


def wait(milli):
    return f"DELAY : {milli}"


def holding(key, then="", thenCommands=[]):
    combination = [keyDown(key)]
    if len(then) > 0:
        combination.append(then)
    if len(thenCommands) > 0:
        combination.append(join(thenCommands))
    combination.append(keyUp(key))
    return join(combination)


def holdingMultiple(keys, then="", thenCommands=[]):
    # TODO: 看看怎么用递归写
    if len(keys) == 1:
        return holding(keys[0], then, thenCommands)
    return holding(keys[0], holdingMultiple(keys[1:], then, thenCommands))


def leftClick():
    return click("Left")


def leftDown():
    return keyDown("Left")


def leftUp():
    return keyUp("Left")


def rightClick():
    return click("Right")


def rightDown():
    return keyDown("Right")


def rightUp():
    return keyUp("Right")


def upDown():
    return keyDown("Up")


def upUp():
    return keyUp("Up")


def downDown():
    return keyDown("Down")


def downUp():
    return keyUp("Down")


def click(button):
    return join([
        keyDown(button),
        wait(INTERVAL_CLICK),
        keyUp(button),
    ])


def clickQuick(button):
    return join([
        keyDown(button),
        wait(50),
        keyUp(button),
    ])


def doubleClick(button):
    return join([
        click(button),
        wait(INTERVAL_CLICK),
        click(button),
    ])


def tripleClick(button):
    return join([
        doubleClick(button),
        wait(INTERVAL_CLICK),
        click(button),
    ])


def baseAttack():
    return join([
        click("F"),
        wait(550)
    ])


def attackBothLeft():
    return join([
        leftClick(),
        baseAttack(),
        rightClick(),
        baseAttack(),
        leftClick()
    ])


def jump():
    return click("G")


def jumpFront():
    combination = [
        jump(),
        wait(INTERVAL_JUMP),
        jump(),
        wait(INTERVAL_CLICK),
        baseAttack(),
    ]
    return join(combination)


def jumpFrontNoAttack():
    return join([
        jump(),
        wait(INTERVAL_JUMP),
        jump(),
        wait(INTERVAL_CLICK),
    ])


def jumpFarFront():
    combination = [
        jump(),
        wait(100),
        jump(),
        wait(INTERVAL_CLICK),
        baseAttack(),
    ]
    return join(combination)


def jumpFarFarRight():
    combination = [
        wait(INTERVAL_CLICK),
        jump(),
        wait(100),
        jump(),
        wait(INTERVAL_CLICK),
        baseAttack(),
    ]
    return holding("Right", then=join(combination))


def jumpFarFarLeft():
    combination = [
        wait(INTERVAL_CLICK),
        jump(),
        wait(100),
        jump(),
        wait(INTERVAL_CLICK),
        baseAttack(),
    ]
    return holding("Left", then=join(combination))


def jumpRightLeftAttack():
    combination = [
        click("Right"),
        jump(),
        wait(INTERVAL_JUMP),
        jump(),
        click("Left"),
        baseAttack(),
        click("Right")
    ]
    return join(combination)


def jumpLeftRightAttack():
    combination = [
        click("Left"),
        jump(),
        wait(INTERVAL_JUMP),
        jump(),
        click("Right"),
        baseAttack(),
        click("Left")
    ]
    return join(combination)


def jumpHighLeft():
    combination = [
        clickQuick("Left"),
        jump(),
        upDown(),
        wait(INTERVAL_JUMP),
        jump(),
        upUp(),
        wait(150),
        baseAttack(),
        clickQuick("Right"),
        baseAttack(),
        clickQuick("Left")
    ]
    return join(combination)


def jumpHighRight():
    combination = [
        clickQuick("Right"),
        jump(),
        upDown(),
        wait(INTERVAL_JUMP),
        jump(),
        upUp(),
        wait(150),
        baseAttack(),
        clickQuick("Left"),
        baseAttack(),
        clickQuick("Right")
    ]
    return join(combination)


def jumpDown():
    return join([
        holding("Down", jump()),
        wait(1000)
    ])


def summonFrenzy():
    return join([
        doubleClick("D3"),
        wait(600)  # 轮回图腾后摇
    ])


def getAllBuffs():
    return join([
        doubleClick("F12"),
        wait(300),
        click("Escape"),
        wait(70)
    ])


def start():
    return join([
        summonFrenzy(),
        getAllBuffs()
    ])


def returnLeft(jumps=5):
    combination = [
        leftClick(),
    ]
    for i in range(jumps):
        combination.append(jumpFront())
    return join(combination)


def returnRight(jumps=5):
    combination = [
        rightClick(),
    ]
    for i in range(jumps):
        combination.append(jumpFront())
    return join(combination)


def slash():
    return join([
        click("H"),
        wait(INTERVAL_SLASH),
        click("D"),
        wait(INTERVAL_SLASH_END)
    ])


def slashLeft():
    return holding("Left", then=slash())


def slashRight():
    return holding("Right", then=slash())


def slashUp():
    return holding("Up", then=slash())


def slashDown():
    return holding("Down", then=slash())


def slashLeftUp():
    return holdingMultiple(keys=["Left", "Up"], then=slash())


def slashRightUp():
    return holdingMultiple(keys=["Right", "Up"], then=slash())


def summonSword():
    return click("R")


def flower():
    return join([
        click("S"),
        wait(400)
    ])


def infinity():
    return join([
        click("Q"),
        wait(700)
    ])


def destroy():
    return join([
        click("X"),
        wait(700)
    ])


def magicBlast():
    return join([
        click("V"),
        wait(700)
    ])


def swordZone():
    return join([
        click("C"),
        wait(700)
    ])


def shard():
    return join([
        click("Z"),
        wait(700)
    ])


def recall():
    return join([
        click("A"),
    ])

def buff(button, interval = 700):
    return join([
        click(button),
        wait(interval)
    ])

def buff1():
    return buff("1")

def buff2():
    return buff("2")

def buff3():
    return buff("3")

def buff4():
    return buff("4")