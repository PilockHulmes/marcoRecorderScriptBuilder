from capture import Capture
import paddleocr
import cv2
from PIL import Image
import time
import numpy as np
import pydirectinput
import pprint

POSITION_BPOT_AGAIN = (657,507)
POSITION_EXIT = (754,507)

XENO_PRIME = [
    "所有属性：+5%",
]

XENO_SEC = [
    "所有属性：+4%",
]

STR_PRIME = [
    "力量：+7%",
    "角色每10级力量：+2",
]

STR_SEC = [
    "力量：+5%",
    "所有属性：+5%",
    "所有属性：+4%",
    "角色每10级力量：+1",
]

DEX_PRIME = [
    "敏捷：+7%",
    "角色每10级敏捷：+2",
]

DEX_SEC = [
    "敏捷：+5%",
    "所有属性：+5%",
    "所有属性：+4%",
    "角色每10级敏捷：+1",
]

INT_PRIME = [
    "智力：+7%",
    "角色每10级智力：+2",
]

INT_SEC = [
    "智力：+5%",
    "所有属性：+5%",
    "所有属性：+4%",
    "角色每10级智力：+1",
]

LUK_PRIME = [
    "运气：+7%",
    "角色每10级运气：+2",
]

LUK_SEC = [
    "运气：+5%",
    "所有属性：+5%",
    "所有属性：+4%",
    "角色每10级运气：+1",
]

class CubeWasher:
    def __init__(self, debug = False):
        self.capture = Capture("MapleStory")
        self.ocr = paddleocr.PaddleOCR(lang='ch', show_log=False)
        self.capture.start()
        self.debug = debug

    def readText(self):
        image = cv2.cvtColor(self.capture.frame, cv2.COLOR_BGRA2RGB) 
        # 610,410 765,485
        # the 410+30 and 485+30 are compensate for the 30px high of the window title
        all_lines = image[410+30:485+30, 610:765]
        all_lines_blacked = self.blackBotText(all_lines)
        b = Image.fromarray(all_lines_blacked)
        b.save("z_cube_washing_all.png") # 426 441 455 469
        all_result = self.ocr.ocr(img=all_lines_blacked)
        print("all:", all_result)
        bpot_lines = []
        if all_result is not None and all_result[0] is not None and len(all_result) > 0 :
            for line in all_result[0]:
                if type(line[1][0]) == str:
                    bpot_lines.append(line[1][0])
        # print(bpot_lines)
        rotated = cv2.rotate(all_lines_blacked, cv2.ROTATE_180)
        b = Image.fromarray(rotated)
        b.save("z_cube_washing_all_rotated.png")
        rotated_all_result = self.ocr.ocr(img=rotated)
        rotated_bpot_lines = []
        if rotated_all_result is not None and rotated_all_result[0] is not None and len(rotated_all_result) > 0 :
            for line in rotated_all_result[0]:
                if type(line[1][0]) == str:
                    rotated_bpot_lines.append(line[1][0])
        return (bpot_lines, rotated_bpot_lines)

    def parseOcrText(self, ocr_result):
        if ocr_result is not None and ocr_result[0] is not None and len(ocr_result) > 0 :
            for line in ocr_result[0]:
                if type(line[1][0]) == str:
                    return line[1][0]

    def readTextLineByLine(self):
        image = cv2.cvtColor(self.capture.frame, cv2.COLOR_BGRA2RGB) 

        border_width = 8
        first_line = image[426 + 30:441 + 30, 610:765]
        first_line_blacked = self.blackBotText(first_line)
        first_extended = cv2.copyMakeBorder(
            src=first_line_blacked, 
            top=border_width,
            bottom=border_width,
            left=border_width,
            right=border_width,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0)  # 黑色（BGR 格式）
        )
        second_line = image[441 + 30:455 + 30, 610:765]
        second_line_blacked = self.blackBotText(second_line)
        second_extended = cv2.copyMakeBorder(
            src=second_line_blacked, 
            top=border_width,
            bottom=border_width,
            left=border_width,
            right=border_width,
            borderType=cv2.BORDER_CONSTANT,
            value=(0, 0, 0)  # 黑色（BGR 格式）
        )
        third_line = image[455 + 30:469 + 30, 610:765]
        third_line_blacked = self.blackBotText(third_line)
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

    def isLuckLines(self, bpot_lines):
        counter = 0
        for line in bpot_lines:
            line_text = str(line)
            if line_text in LUK_PRIME or line_text in LUK_SEC:
                counter += 1
        print(bpot_lines, counter)
        return counter >= 3

    def isLuckTwoLines(self, bpot_lines):
        prime = 0
        secondary = 0
        for line in bpot_lines:
            line_text = str(line)
            if line_text in LUK_PRIME:
                prime += 1
            if line_text in LUK_SEC:
                secondary += 1
        print(bpot_lines, prime, secondary)
        return (prime >= 1 and prime + secondary >= 2) or (secondary >= 3)

    def isAnyThreeLines(self, bpot_lines):
        counter = {
            "XENO": 0,
            "STR": 0,
            "DEX": 0,
            "INT": 0,
            "LUK": 0,
        }
        for line in bpot_lines:
            line_text = str(line)
            if line_text in XENO_PRIME or line_text in XENO_SEC:
                counter["XENO"] += 1
            if line_text in STR_PRIME or line_text in STR_SEC:
                counter["STR"] += 1
            if line_text in DEX_PRIME or line_text in DEX_SEC:
                counter["DEX"] += 1
            if line_text in INT_PRIME or line_text in INT_SEC:
                counter["INT"] += 1
            if line_text in LUK_PRIME or line_text in LUK_SEC:
                counter["LUK"] += 1
        print(bpot_lines)
        pprint.pprint(counter, indent=4)
        for stats, c in counter.items():
            if c >= 3:
                return True
        return False

    def isSellableThreeLines(self, bpot_lines):
        prime = {
            "XENO": 0,
            "STR": 0,
            "DEX": 0,
            "INT": 0,
            "LUK": 0,
        }
        sec = {
            "XENO": 0,
            "STR": 0,
            "DEX": 0,
            "INT": 0,
            "LUK": 0,
        }
        for line in bpot_lines:
            line_text = str(line)
            if line_text in XENO_PRIME:
                prime["XENO"] += 1
            if line_text in XENO_SEC:
                sec["XENO"] += 1
            if line_text in STR_PRIME:
                prime["STR"] += 1
            if line_text in STR_SEC:
                sec["STR"] += 1
            if line_text in DEX_PRIME:
                prime["DEX"] += 1
            if line_text in DEX_SEC:
                sec["DEX"] += 1
            if line_text in INT_PRIME:
                prime["INT"] += 1
            if line_text in INT_SEC:
                sec["INT"] += 1
            if line_text in LUK_PRIME:
                prime["LUK"] += 1
            if line_text in LUK_SEC:
                sec["LUK"] += 1
        print(bpot_lines)
        pprint.pprint(prime, indent=4)
        pprint.pprint(sec, indent=4)
        for stats, c in prime.items():
            if c >= 2 and sec[stats] >= 1:
                return True
        return False


    def bpotAgain(self):
        if self.debug:
            for i in range(3):
                print("count down:", i + 1)
                time.sleep(1)
        pydirectinput.click(POSITION_BPOT_AGAIN[0] + self.capture.window["left"], POSITION_BPOT_AGAIN[1] + self.capture.window["top"] + 30)
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
    
    washer.readTextLineByLine()