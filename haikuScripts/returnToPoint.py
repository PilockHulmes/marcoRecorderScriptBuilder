import threading
import time
from capture import Capture
import config as config
import commandBuilderLib as lib
import pydirectinput

DOUBLE_JUMP = 0.15
TRIPLE_JUMP = 0.25

UPPER_JUMP = 0.05
DOUBLE_UPPER_JUMP = 0.15

WALKING_PER_SECOND = 0.097 # roughly tested, with 150 character speed

class Return:
    def __init__(self, horizontal_threshold = 0.01,vertical_threshold = 0.02):
        self.capture = Capture()
        self.points = {}
        self.distance_horizontal = 0
        self.distance_vertical = 0
        self.horizontal_threshold = horizontal_threshold
        self.vertical_threshold = vertical_threshold
    
    def start(self):
        self.capture.start()
    
    def save(self, index=0):
        self.points[index] = config.player_position

    def returnToSavePoint(self, index=0):
        while True:
            self.calculateDistance(index)
            if self.verticalMatch() and self.horizontalMatch():
                break
            if not self.horizontalMatch():
                self.approachHorizontal()
                continue
            if not self.verticalMatch():
                self.approachVertical()
                continue

    def calculateDistance(self, index = 0):
        self.distance_horizontal = self.points[index][0] - config.player_position[0]
        self.distance_vertical = self.points[index][1] - config.player_position[1]
        print("saved:", self.points[index])
        print("player:", config.player_position)
        print(self.distance_horizontal)
        print(self.distance_vertical)
        print("Having bot testing:", config.bottesting)

    def verticalMatch(self):
        return abs(self.distance_vertical) <= self.vertical_threshold
    
    def horizontalMatch(self):
        return abs(self.distance_horizontal) <= self.horizontal_threshold

    def approachHorizontal(self):
        if self.horizontalMatch():
            return
        direction = ""
        if self.distance_horizontal > 0: # go right
            direction = "right"
        else: # go left 
            direction = "left"
        distance = abs(self.distance_horizontal)
        if distance > TRIPLE_JUMP:
            lib.keyboardClick(direction)
            time.sleep(0.05)
            lib.tribleJump()
            time.sleep(0.1)
        elif distance > DOUBLE_JUMP:
            lib.keyboardClick(direction)
            time.sleep(0.05)
            lib.doubleJump()
            time.sleep(0.1)
        else:
            duration = distance / WALKING_PER_SECOND
            print("distance", distance)
            print("duration", duration)
            pydirectinput.keyDown(direction)
            lib.delay(duration - 0.1) # minus 0.1 to compensate the delay of python input library
            pydirectinput.keyUp(direction)
            # give time to stop walking
            time.sleep(0.1)
        # internal pause
        time.sleep(0.05)

    def approachVertical(self):
        if self.verticalMatch():
            return
        direction = ""
        if self.distance_vertical > 0: # go down
            lib.downJump()
            time.sleep(0.1)
        else: # go up
            distance = abs(self.distance_vertical)
            if distance > DOUBLE_UPPER_JUMP:
                lib.doubleHighJump()
                time.sleep(0.1)
            elif distance > UPPER_JUMP:
                lib.highJump()
                time.sleep(0.1)
            else: # actually, we don't know what should we do at this time, so just jump once
                lib.jump()
                time.sleep(0.05)
        # internal pause
        time.sleep(0.05)
        