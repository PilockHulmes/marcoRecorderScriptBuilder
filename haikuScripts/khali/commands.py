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
        # print(func.__name__)
        func(*args, **kwargs)
    return wrapper

def oppositeDirection(direction = "left"):
    if direction == "left":
        return "right"
    else:
        return "left"

def sleep(duration):
    windows_interval = 0.03
    start = time.perf_counter()
    if duration > windows_interval:
        time.sleep(duration - windows_interval)  # 先睡眠大部分时间
    while time.perf_counter() - start < duration:
        pass  # 微调剩余时间

@stopIfNotRunning
@callMyName
def hold(key, duration):
    pydirectinput.keyDown(key)
    time.sleep(duration)
    pydirectinput.keyUp(key)

@stopIfNotRunning
@callMyName
def click(key):
    pydirectinput.keyDown(key)
    pydirectinput.keyUp(key)

def buffFactory(key, sleep_time = 0):
    @stopIfNotRunning
    def func():
        if sleep_time > 0:
            time.sleep(sleep_time)
        click(key)
        time.sleep(1)
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
def jumpSlash(direction = None, wait_for_after_animation = True):
    if direction != None:
        pydirectinput.keyDown(direction)    
    jump()
    slash()
    if direction != None:
        pydirectinput.keyUp(direction)
    if wait_for_after_animation:
        time.sleep(0.2)

@stopIfNotRunning
@callMyName
def doubleJumpBackwardSlash(direction = "left"):
    faceDirection(direction)
    doubleJump()
    faceDirection(oppositeDirection(direction))
    slash()
    time.sleep(0.3)
    faceDirection(direction)

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
def downJumpSlash(wait_for_after_animation = True):
    downJump()
    # TODO: decide how long to slash
    slash()
    if (wait_for_after_animation):
        time.sleep(0.4)


@stopIfNotRunning
@callMyName
def flowering():
    click("w")
    click("w")
    time.sleep(0.5)

@stopIfNotRunning
@callMyName
def ring(wait_for_after_animation = True):
    click("h")
    if wait_for_after_animation:
        time.sleep(0.33)

@stopIfNotRunning
@callMyName
def fury(wait_for_after_animation = True):
    click("r")
    if wait_for_after_animation:
        time.sleep(0.6)

last_use_fountain = time.time() - 60
@stopIfNotRunning
@callMyName
def fountain(wait_for_after_animation = True):
    global last_use_fountain
    pydirectinput.keyDown("down")
    click("t")
    pydirectinput.keyUp("down")
    last_use_fountain = time.time()
    if wait_for_after_animation:
        time.sleep(0.6)

last_use_janus = time.time() - 60
@stopIfNotRunning
@callMyName
def janus(wait_for_after_animation = True):
    global last_use_janus
    click("y")
    last_use_janus = time.time()
    if wait_for_after_animation:
        time.sleep(0.6)

last_use_blossom = time.time() - 60
@stopIfNotRunning
@callMyName
def blossom(wait_for_after_animation = True):
    global last_use_blossom
    click("w")
    last_use_blossom = time.time()
    if wait_for_after_animation:
        time.sleep(0.8)

@stopIfNotRunning
@callMyName
def doubleJumpBackwardRing(direction = "left"):
    faceDirection(direction)
    doubleJump()
    faceDirection(oppositeDirection(direction))
    ring()
    faceDirection(direction)

@stopIfNotRunning
@callMyName
def doubleJumpForwardRing(direction = "left"):
    faceDirection(direction)
    doubleJump()
    ring()

@stopIfNotRunning
@callMyName
def tripleJumpForwardRing(direction = "left"):
    faceDirection(direction)
    tripleJump()
    ring()

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

def returnTrueWithInterval(interval_in_seconds, initial_return_true = False):
    if initial_return_true:
        start = time.time() - interval_in_seconds - 1
    else:
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

rotateIntervalPool = {}
def rotateWithInterval(func, backup, interval_in_seconds, pool_index = 0):
    @stopIfNotRunning
    def innerfunc():
        if pool_index not in rotateIntervalPool:
            rotateIntervalPool[pool_index] = time.time()
            func()
            return True
        if time.time() - rotateIntervalPool[pool_index] >= interval_in_seconds:
            rotateIntervalPool[pool_index] = time.time()
            func()
            return True
        else:
            backup()
            return False
    return innerfunc

multiRotateIntervalPool = {}
def multiRotateWithInterval(funcs, pool_index = 0):
    @stopIfNotRunning
    def innerfunc():
        for i, (func, interval) in enumerate(funcs):
            if pool_index not in multiRotateIntervalPool:
                multiRotateIntervalPool[pool_index] = time.time()
                func()
                return True
            if time.time() - multiRotateIntervalPool[pool_index] >= interval:
                multiRotateIntervalPool[pool_index] = time.time()
                func()
                return True
        return False
    return innerfunc

def skillOnCooldown(last_used_time, cd_in_sec):
    if last_used_time == None:
        return True
    return time.time() - last_used_time > cd_in_sec