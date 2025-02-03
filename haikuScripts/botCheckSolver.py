import cv2
import easyocr
from capture import Capture
from PIL import Image
import numpy as np
from paddleocr import PaddleOCR

# for haiku
class BotSolver:
    def __init__(self, capture: Capture):
        self.capture = capture
        self.botText = ""
        # self.reader = easyocr.Reader(['en'], gpu=True)
        # paddle ocr yields better result
        self.reader = PaddleOCR(use_angle_cls=True, lang='en')
    
    def hasBotCheck(self):
        return self.botText != "" and self.botText.startswith("@bot")
    
    # manually clear the bot text so it can check again
    def clearBotText(self):
        self.botText = ""

    def getBotText(self):
        image = self.capture.frame
        # image = cv2.imread('../bot2.png')
        # 1040,520 1200,555 text position, need to minus window position left,top 544,93
        cropped = image[520 - 93 : 555 - 93, 1040 - 544 : 1200 - 544]
        blacked = self.blackBotText(cropped)
        # results[page][line][0 for numbers, 1 for text and accuracy][0 for text, 1 for accuracy float]
        results = self.reader.ocr(blacked, cls=True)
        print("bot result:", results)
        if len(results) > 0 and results[0][0][1][0].startswith("@bot"):
            self.botText = results[0][0][1][0]
            b = Image.fromarray(blacked)
            b.save("z_latest_bot_text.png")
        return self.botText
    
    def blackBotText(self, image):
        # 定义白色的范围（BGR格式）
        lower_white = np.array([220, 220, 220])  # 接近白色的下限
        upper_white = np.array([255, 255, 255])  # 白色的上限

        # 创建掩码，标记白色区域
        mask = cv2.inRange(image, lower_white, upper_white)

        # 将非白色区域变为黑色
        result = image.copy()
        result[mask == 0] = 0  # 掩码为0的区域（非白色）设置为黑色
        return result

    def needSolveRune(self):
        # image = self.capture.frame
        image = cv2.imread('../rune1.png')
        # 0,660 400,760 chatbox which is placed in the bottom left and shows 5 rows of texts
        cropped = image[660:760, 0:400]
        c = Image.fromarray(cropped)
        c.save("z_latest_chatbox.png")
        # results[page][line][0 for numbers, 1 for text and accuracy][0 for text, 1 for accuracy float]
        results = self.reader.ocr(cropped)
        # print(results)
        all_texts = ""
        for line in results[0]:
            all_texts += line[1][0]
        # print(all_texts)
        return "must activate the Runestone" in all_texts

    def debug(self):
        image = cv2.imread('z_latest_bot_text.png')
        results = self.reader.readtext(image)
        print(results)