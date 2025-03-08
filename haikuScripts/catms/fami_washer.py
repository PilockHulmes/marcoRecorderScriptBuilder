from capture import Capture
import paddleocr
import cv2
from PIL import Image
import time
import numpy as np
import pydirectinput
import pprint

ATT_LINE = "物理攻击力：+14%"
MATT_LINE = "魔法攻击力：+14%"
IED_LINE = "攻击时无视怪物的防御力45%"

class FamiWasher:
    def __init__(self, debug = False):
        self.capture = Capture("MapleStory")
        self.ocr = paddleocr.PaddleOCR(lang='ch', show_log=False)
        self.capture.start()
    
    def blackBotText(self, image):
        # print(image)
        # 定义白色的范围（BGR格式）
        lower_white = np.array([220, 220, 180])  # 接近白色的下限
        upper_white = np.array([255, 255, 255])  # 白色的上限

        # 创建掩码，标记白色区域
        mask = cv2.inRange(image, lower_white, upper_white)

        # 将非白色区域变为黑色
        result = image.copy()
        result[mask == 0] = 0  # 掩码为0的区域（非白色）设置为黑色
        return result

    def readTextLineByLine(self):
        # (459, 471) 485 498 511
        # (663, 512)

        image = cv2.cvtColor(self.capture.frame, cv2.COLOR_BGRA2RGB)
        first_line = image[471+30:485+30, 465:663]
        second_line = image[485+30:498+30, 465:663]
        third_line = image[498+30:511+30, 465:663]

        first_line_blacked = self.blackBotText(first_line)
        second_line_blacked = self.blackBotText(second_line)
        third_line_blacked = self.blackBotText(third_line)

        border_width = 8 # px
        first_extended = cv2.copyMakeBorder(
            src=first_line_blacked, 
            top=border_width,
            bottom=border_width,
            left=border_width,
            right=border_width,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0)  # 黑色（BGR 格式）
        )
        second_extended = cv2.copyMakeBorder(
            src=second_line_blacked, 
            top=border_width,
            bottom=border_width,
            left=border_width,
            right=border_width,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0)  # 黑色（BGR 格式）
        )
        third_extended = cv2.copyMakeBorder(
            src=third_line_blacked, 
            top=border_width,
            bottom=border_width,
            left=border_width,
            right=border_width,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0)  # 黑色（BGR 格式）
        )
        
        b = Image.fromarray(first_extended)
        b.save("z_first_extended.png")
        b = Image.fromarray(second_extended)
        b.save("z_second_extended.png")
        b = Image.fromarray(third_extended)
        b.save("z_third_extended.png")

        return [
            self.parseOcrText(self.ocr.ocr(img=first_extended)),
            self.parseOcrText(self.ocr.ocr(img=second_extended)),
            self.parseOcrText(self.ocr.ocr(img=third_extended)),
        ]

    def parseOcrText(self, ocr_result):
        if ocr_result is not None and ocr_result[0] is not None and len(ocr_result) > 0 :
            for line in ocr_result[0]:
                if type(line[1][0]) == str:
                    return line[1][0]

    # (1021, 70) 怪怪魔方放第一个，物品栏贴着怪怪UI放最右上角
    def wash(self, fami_pos):
        left = self.capture.window["left"]
        top = self.capture.window["top"]
        pydirectinput.doubleClick(1021 + left, 70 + top + 30)
        time.sleep(0.2)
        pydirectinput.click(fami_pos[0] + left, fami_pos[1] + top + 30)
        time.sleep(0.2)
        pydirectinput.press("enter")
        time.sleep(0.2)
    
    def isAttLines(self, fami_lines):
        att = 0
        ied = 0
        for line in fami_lines:
            if line == ATT_LINE:
                att += 1
            if line == IED_LINE:
                ied += 1
        print(fami_lines, att, ied)
        return att >= 3 or (att >= 2 and ied >= 1)
    
    def isMattLines(self, fami_lines):
        matt = 0
        for line in fami_lines:
            if line == MATT_LINE:
                matt += 1
        print(fami_lines, matt)
        return matt >=3



if __name__ == '__main__':
    washer = FamiWasher()
    # 等三秒初始化
    time.sleep(3)
    
    washer.readTextLineByLine()