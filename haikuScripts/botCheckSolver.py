import cv2
from capture import Capture
from PIL import Image
import numpy as np
from paddleocr import PaddleOCR
import logging
import time

# for haiku
class BotSolver:
    def __init__(self, capture: Capture, rune_text = "must activate the Runestone", ocr_lang = "en", ignore_text_duration = 0):
        self.capture = capture
        self.bot_text = ""
        self.rune_text = rune_text
        # self.reader = easyocr.Reader(['en'], gpu=True)
        # paddle ocr yields better result
        # 设置日志级别为 ERROR
        logging.getLogger('ppocr').setLevel(logging.ERROR)
        self.reader = PaddleOCR(lang=ocr_lang)
        self.rune_text = rune_text
        self.start_time = time.time()
        self.ignore_text_duration = ignore_text_duration
        self.print_solve_rune_countdown = time.time()
    
    def hasBotCheck(self):
        return self.bot_text != "" and self.bot_text.startswith("@bot")
    
    # manually clear the bot text so it can check again
    def clearBotText(self):
        self.bot_text = ""

    def getBotText(self):
        image = cv2.cvtColor(self.capture.frame, cv2.COLOR_BGRA2BGR) 
        # image = cv2.imread('../bot2.png')
        # 1040,520 1200,555 text position, need to minus window position left,top 544,93.
        # and need to minus title height 30px
        cropped = image[460 - 93 - 40 : 635 - 93 - 40, 1040 - 544 : 1450 - 544]
        b = Image.fromarray(cropped)
        b.save("z_latest_cropped_bot_text.png")
        blacked = self.blackBotText(cropped)
        b = Image.fromarray(blacked)
        b.save("z_latest_blacked_bot_text.png")
        # results[page][line][0 for numbers, 1 for text and accuracy][0 for text, 1 for accuracy float]
        results = self.reader.ocr(blacked)
        print("bot result:", results)
        if results is not None and results[0] is not None and len(results) > 0 :
            for line in results[0]:
                if type(line[1][0]) == str and line[1][0].startswith("@bot"):
                    self.bot_text = line[1][0]
                    print("bot text:", self.bot_text)
                    b = Image.fromarray(blacked)
                    b.save("z_latest_bot_text.png")
        return self.bot_text
    
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

    def needSolveRune(self):
        # 在前几分钟不管，避免历史数据一直警报
        if time.time() - self.start_time <= self.ignore_text_duration:
            return
        image = self.capture.frame
        # image = cv2.imread('../rune1.png')
        # 0,660 400,760 chatbox which is placed in the bottom left and shows 5 rows of texts
        cropped = image[660:760, 0:400]
        c = Image.fromarray(cropped)
        c.save("z_latest_chatbox.png")
        # results[page][line][0 for numbers, 1 for text and accuracy][0 for text, 1 for accuracy float]
        results = self.reader.ocr(cropped)
        # print(results)
        all_texts = ""
        if results is not None and results[0] is not None:
            for line in results[0]:
                all_texts += line[1][0]

        if time.time() - self.print_solve_rune_countdown >= 60:
            self.print_solve_rune_countdown = time.time()
            print(all_texts)
        return self.rune_text in all_texts

    def debug(self):
        image = cv2.imread('z_latest_bot_text.png')
        results = self.reader.readtext(image)
        print(results)