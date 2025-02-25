from capture import Capture
from paddleocr import PaddleOCR
import cv2
from PIL import Image
import time
import numpy as np
import pydirectinput

POSITION_BPOT_AGAIN = (997,622)
POSITION_EXIT = (1081,619)

class CubeWasher:
    def __init__(self):
        self.capture = Capture("MapleStory")
        self.ocr = PaddleOCR(lang='ch')
        self.capture.start()

    def readText(self):
        image = cv2.cvtColor(self.capture.frame, cv2.COLOR_BGRA2RGB) 
        # 610,410 765,485
        # the 410+30 and 485+30 are compensate for the 30px high of the window title
        all_lines = image[410+30:485+30, 610:765]
        all_lines_blacked = self.blackBotText(all_lines)
        b = Image.fromarray(all_lines_blacked)
        b.save("z_cube_washing_all.png")
        all_result = self.ocr.ocr(img=all_lines_blacked ,cls=False)
        print("all:", all_result)
        bpot_lines = []
        if all_result is not None and all_result[0] is not None and len(all_result) > 0 :
            for line in all_result[0]:
                if type(line[1][0]) == str:
                    bpot_lines.append(line[1][0])
        print(bpot_lines)
        return bpot_lines

    def blackBotText(self, image):
        # print(image)
        # 定义白色的范围（BGR格式）
        lower_white = np.array([220, 220, 220])  # 接近白色的下限
        upper_white = np.array([255, 255, 255])  # 白色的上限

        # 创建掩码，标记白色区域
        mask = cv2.inRange(image, lower_white, upper_white)

        # 将非白色区域变为黑色
        result = image.copy()
        result[mask == 0] = 0  # 掩码为0的区域（非白色）设置为黑色
        return result
    
    def isThreeLineAttack(self, bpot_lines):
        for line in bpot_lines:
            if str(line).split("：") != "攻击力":
                return False
        return True

    def isTwoLineAttack(self, bpot_lines):
        counter = 0
        for line in bpot_lines:
            if str(line).split("：")[0] == "攻击力":
                counter += 1
        return counter >= 2

    def bpotAgain(self):
        pydirectinput.click(POSITION_BPOT_AGAIN[0], POSITION_BPOT_AGAIN[1])
        pydirectinput.keyDown("enter")
        pydirectinput.keyUp("enter")
        pydirectinput.keyDown("enter")
        pydirectinput.keyUp("enter")
        pydirectinput.keyDown("enter")
        pydirectinput.keyUp("enter")

    def parseResults(self, bpot_lines):
        pass
                                  

if __name__ == '__main__':
    washer = CubeWasher()
    # 等三秒初始化
    time.sleep(3)
    
