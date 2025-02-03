import cv2
import easyocr
from capture import Capture
from PIL import Image

# for haiku
class BotSolver:
    def __init__(self, capture: Capture):
        self.capture = capture
        self.botText = ""
        self.reader = easyocr.Reader(['en'])
    
    def hasBotCheck(self):
        return self.botText != "" and self.botText.startswith("@bot")
    
    # manually clear the bot text so it can check again
    def clearBotText(self):
        self.botText = ""

    def getBotText(self):
        # image = self.capture.frame
        image = cv2.imread('../bot2.png')
        # 1040,520 1200,555 text position, need to minus window position left,top 544,93
        cropped = image[520 - 93 : 555 - 93, 1040 - 544 : 1200 - 544]
        results = self.reader.readtext(cropped)
        print("bot result:", results)
        if len(results) > 0 and results[0][1].startswith("@bot"):
            self.botText = results[0][1]
            c = Image.fromarray(cropped)
            c.save("z_latest_bot_text.png")
        return self.botText
    
    def needSolveRune(self):
        image = self.capture.frame
        # 0,660 400,760 chatbox which is placed in the bottom left and shows 5 rows of texts
        cropped = image[660:760, 0:400]
        c = Image.fromarray(cropped)
        c.save("z_latest_chatbox.png")
        results = self.reader.readtext(cropped)
        all_texts = ""
        for _, text, _ in results:
            all_texts += (" " + text)
        # print(all_texts)
        return "Runestone" in all_texts and "You must" in all_texts

    def debug(self):
        image = cv2.imread('z_latest_bot_text.png')
        results = self.reader.readtext(image)
        print(results)