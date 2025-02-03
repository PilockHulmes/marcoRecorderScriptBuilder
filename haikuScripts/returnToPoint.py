import threading
import time
from capture import Capture
import config as config
import commandBuilderLib as lib
import pydirectinput
import detection
import cv2
from PIL import Image
import pygame
import threading
from botCheckSolver import BotSolver


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
        self.model = detection.load_model()
        self.botSolver = BotSolver(self.capture) 
    
    def start(self):
        self.capture.start()
        self.startWarningThread()
    
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
    
    def startWarningThread(self):
        thread = threading.Thread(target=self.warningThreadMain)
        thread.daemon = True
        thread.start()

    def warningThreadMain(self):
        pygame.mixer.init()
        # # wait for 10s at the begining so the capture could init properly
        # time.sleep(10)
        while True:
            time.sleep(2)
            if self.needSolveRune():
                self.playsound("assets/alerts/rune_appeared.mp3")
            if self.hasPplInMap():
                self.playsound("assets/alerts/ding.mp3")

    def needSolveRune(self):
        # still has rune buff, so no need to solve rune
        if not self.botSolver.needSolveRune():
            return False
        # no rune in the map, no need to solve rune
        if config.rune_position is None:
            return False
        return True

    def hasPplInMap(self):
        return config.map_invaded
    
    def playsound(self, path):
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()

        # 等待播放完成（可选）
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(100)

    def botTesting(self):
        text = self.botSolver.getBotText()
        if text.startswith("@bot"):
            # close the dialogue with enter
            time.sleep(0.5)
            lib.keyboardClick("enter")
            time.sleep(0.5)
            lib.switchToSpeak()
            lib.keyboardClick("enter")
            time.sleep(0.5)
            lib.inputAt()
            time.sleep(0.2)
            lib.inputText(text)
            time.sleep(0.5)
            lib.keyboardClick("enter")
        self.botSolver.clearBotText()

    def solveRune(self):
        # print(self.capture.frame)
        # image = Image.fromarray(self.capture.frame)
        # image.save("output.png")
        # cv2.imshow('img', self.capture.frame)
        arrows = detection.merge_detection(self.model, self.capture.frame)
        print(arrows)
        # arrows = detection.find_arrow_directions(self.capture.frame, False)
        # print(arrows)

    def calculateDistance(self, index = 0):
        self.distance_horizontal = self.points[index][0] - config.player_position[0]
        self.distance_vertical = self.points[index][1] - config.player_position[1]
        # print("saved:", self.points[index])
        # print("player:", config.player_position)
        # print(self.distance_horizontal)
        # print(self.distance_vertical)

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
        