import pydirectinput
import time
from pynput import keyboard


running = True
stop_key = "l"
def stopWhenPress(pressed_key):
    global running
    try:
        if pressed_key.char == stop_key:
            running = False
            return False
    except AttributeError:
        pass

listener = keyboard.Listener(on_press=stopWhenPress)
listener.start()

def stopIfNotRunning(func):
    global running
    def wrapper(*args, **kwargs):
        if not running:
            return
        func(*args, **kwargs)
    return wrapper

def callMyName(func):
    def wrapper(*args, **kwargs):
        print(func.__name__)
        func(*args, **kwargs)
    return wrapper

def oppositeDirection(direction = "left"):
    if direction == "left":
        return "right"
    else:
        return "left"

@stopIfNotRunning
@callMyName
def click(key):
    pydirectinput.keyDown(key)
    pydirectinput.keyUp(key)

def buffFactory(key):
    @stopIfNotRunning
    def func():
        click(key)
        time.sleep(0.8)
    return func

@stopIfNotRunning
@callMyName
def horizontalDash(times = 3, direction = "left"):
    pydirectinput.keyDown(direction)
    i = 0
    while i < times:
        pydirectinput.keyDown("d")
        time.sleep(0.12)
        # dash 3 次刷新一次
        if (i+1)%3 == 0:
            pydirectinput.keyDown("space")
            pydirectinput.keyUp("space")
        i += 1
    # 最后一轮 dash 超过两次，再刷新一次
    if i%3 > 1:
            if i/3 >= 1: # 如果超过1轮，那可能CD还没好所以等一下下
                time.sleep(0.2)
            pydirectinput.keyDown("space")
            pydirectinput.keyUp("space")
    pydirectinput.keyUp(direction)
    pydirectinput.keyUp("d")



@stopIfNotRunning
@callMyName
def dashLeft(times = 3):
    horizontalDash(times, "left")

@stopIfNotRunning
@callMyName
def dashRight(times = 3):
    horizontalDash(times, "right")

@stopIfNotRunning
@callMyName
def faceDirection(direction = "left"):
    pydirectinput.keyDown(direction)
    pydirectinput.keyUp(direction)

@stopIfNotRunning
@callMyName
def slash():
    pydirectinput.keyDown("f")
    pydirectinput.keyUp("f")

@stopIfNotRunning
@callMyName
def refresh():
    pydirectinput.keyDown("space")
    pydirectinput.keyUp("space")

@stopIfNotRunning
@callMyName
def jump():
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")

@stopIfNotRunning
@callMyName
def doubleJump():
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")

@stopIfNotRunning
@callMyName
def tripleJump():
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")

@stopIfNotRunning
@callMyName
def upJump():
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    pydirectinput.keyDown("up")
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("g")
    pydirectinput.keyUp("up")

@stopIfNotRunning
@callMyName
def downJump():
    pydirectinput.keyDown("down")
    pydirectinput.keyDown("g")
    pydirectinput.keyUp("down")
    pydirectinput.keyUp("g")

@stopIfNotRunning
@callMyName
def jumpDash(times = 3, direction = "left"):
    faceDirection(direction)
    jump()
    # TODO: decide how long to dash
    horizontalDash(times, direction)

@stopIfNotRunning
@callMyName
def doubleJumpDash(times = 3, direction = "left"):
    faceDirection(direction)
    doubleJump()
    # TODO: decide how long to dash
    horizontalDash(times, direction)

@stopIfNotRunning
@callMyName
def jumpDownDash():
    jump()
    pydirectinput.keyDown("down")
    pydirectinput.keyDown("d")
    pydirectinput.keyUp("d")
    pydirectinput.keyUp("down")
    time.sleep(0.1)
    click("space")

@stopIfNotRunning
@callMyName
def upJumpDash(times = 3, direction = "left"):
    faceDirection(direction)
    upJump()
    # TODO: decide how long to dash
    horizontalDash(times, direction)

@stopIfNotRunning
@callMyName
def doubleJumpSlash(direction = None):
    if direction != None:
        pydirectinput.keyDown(direction)
    doubleJump()
    # TODO: decide how long to slash
    slash()
    if direction != None:
        pydirectinput.keyUp(direction)

@stopIfNotRunning
@callMyName
def tripleJumpSlash(direction = None):
    if direction != None:
        pydirectinput.keyDown(direction)
    tripleJump()
    # TODO: decide how long to slash
    slash()
    if direction != None:
        pydirectinput.keyUp(direction)

@stopIfNotRunning
@callMyName
def upJumpSlash(direction = None):
    if direction != None:
        pydirectinput.keyDown(direction)
    upJump()
    # TODO: decide how long to slash
    slash()
    if direction != None:
        pydirectinput.keyUp(direction)

@stopIfNotRunning
@callMyName
def downJumpSlash():
    downJump()
    # TODO: decide how long to slash
    slash()

@stopIfNotRunning
@callMyName
def doubleJumpBackRing(direction = "left"):
    faceDirection(direction)
    doubleJump()

def callWithInterval(func, interval_in_seconds):
    start = None
    @stopIfNotRunning
    def innerfunc():
        nonlocal start
        if start is None:
            start = time.time()
            func()
            return True
        if time.time() - start >= interval_in_seconds:
            start = time.time()
            func()
            return True
        return False
    return innerfunc

def returnTrueWithInterval(interval_in_seconds):
    start = None
    def innerFunc():
        nonlocal start
        if start is None:
            start = time.time()
        if time.time() - start >= interval_in_seconds:
            start = time.time()
            return True
        return False
    return innerFunc