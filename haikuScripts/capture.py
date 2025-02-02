import time
import cv2
import threading
import ctypes
import mss
import mss.windows
import numpy as np
import utils as utils 
import config as config
import os

from ctypes import wintypes
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

# The distance between the top of the minimap and the top of the screen
MINIMAP_TOP_BORDER = 5

# The thickness of the other three borders of the minimap
MINIMAP_BOTTOM_BORDER = 9

# Offset in pixels to adjust for windowed mode
WINDOWED_OFFSET_TOP = 36
WINDOWED_OFFSET_LEFT = 10

# The top-left and bottom-right corners of the minimap
MINIMAP_TOPLEFT_TEMPLATE = cv2.imread('assets/minimap_tl_template.png', 0)
MINIMAP_BOTTOMRIGHT_TEMPLATE = cv2.imread('assets/minimap_br_template.png', 0)

MINIMAP_TEMPLATE_HEIGHT = max(MINIMAP_TOPLEFT_TEMPLATE.shape[0], MINIMAP_BOTTOMRIGHT_TEMPLATE.shape[0])
MINIMAP_TEMPLATE_WIDTH = max(MINIMAP_TOPLEFT_TEMPLATE.shape[1], MINIMAP_BOTTOMRIGHT_TEMPLATE.shape[1])

PLAYER_TEMPLATE = cv2.imread('assets/player_template.png', 0)
PLAYER_TEMPLATE_HEIGHT, PLAYERER_TEMPLATE_WIDTH = PLAYER_TEMPLATE.shape

HAIKU_BOT_TESTING_TOPLEFT_TEMPLATE = cv2.imread('assets/haiku_bot_testing_tl_template.jpg', 0)
HAIKU_BOT_TESTING_BOTTOMRIGHT_TEMPLATE = cv2.imread('assets/haiku_bot_testing_br_template.jpg', 0)

HAIKU_BOT_TESTING_HEIGHT = max(HAIKU_BOT_TESTING_TOPLEFT_TEMPLATE.shape[0], HAIKU_BOT_TESTING_BOTTOMRIGHT_TEMPLATE.shape[0])
HAIKU_BOT_TESTING_WIDTH = max(HAIKU_BOT_TESTING_TOPLEFT_TEMPLATE.shape[1], HAIKU_BOT_TESTING_BOTTOMRIGHT_TEMPLATE.shape[1])

# A rune's symbol on the minimap
RUNE_RANGES = (
    ((141, 148, 245), (146, 158, 255)),
)
rune_filtered = utils.filter_color(cv2.imread('assets/rune_template.png'), RUNE_RANGES)
RUNE_TEMPLATE = cv2.cvtColor(rune_filtered, cv2.COLOR_BGR2GRAY)

RUNE_BUFF_TEMPLATE = cv2.imread('assets/rune_buff_template.jpg', 0)

# Other players' symbols on the minimap
OTHER_RANGES = (
    ((0, 245, 215), (10, 255, 255)),
)
other_filtered = utils.filter_color(cv2.imread('assets/other_template.png'), OTHER_RANGES)
OTHER_TEMPLATE = cv2.cvtColor(other_filtered, cv2.COLOR_BGR2GRAY)

WINDOW_NAME = 'Haiku v236 (x64)'

class Capture:

    def __init__(self):
        config.capture = self

        self.window = {
            'left': 0,
            'top': 0,
            'width': 1366,
            'height': 768
        }
        self.minimap_ratio = 1
        self.minimap_sample = None
        self.calibrated = False
        self.screenshoter = None
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True
        self.minimap_topleft_position = None
        self.minimap_bottomright_position = None
        self.haiku_bot_testing_topleft_position = None
        self.haiku_bot_testing_bottomright_position = None
        # np array that represents a screenshot. Its the cv2 BGR format rather than normal RGB
        self.frame = None
    
    def start(self):
        print("Start the video capture")
        self.thread.start()
    
    def _main(self):
        mss.windows.CAPTUREBLT = 0
        while True:
            with mss.mss() as self.screenshoter:
                self.calibrate()
                while True:
                    if not self.calibrated:
                        print("not calibrated properly, redo it")
                        break
                    
                    # Take screenshot
                    self.frame = self.screenshot()
                    if self.frame is None:
                        continue

                    # Crop the frame to only show the minimap
                    minimap = self.frame[self.minimap_topleft_position[1]:self.minimap_bottomright_position[1], self.minimap_topleft_position[0]:self.minimap_bottomright_position[0]]
                    config.minimap = minimap

                    # Determine the player's position
                    player = utils.multi_match(minimap, PLAYER_TEMPLATE, threshold=0.8)
                    if player:
                        config.player_position = utils.convert_to_relative(player[0], minimap)
                    else:
                        config.player_position = (0, 0)
                    
                    # Determin the rune's position
                    filtered = utils.filter_color(minimap, RUNE_RANGES)
                    rune = utils.multi_match(filtered, RUNE_TEMPLATE, threshold=0.9)
                    if rune:
                        config.rune_position = utils.convert_to_relative(rune[0], minimap)
                        config.rune_active = True
                    else:
                        # do nothing to inactive the rune, inactive will be done by rune solver class
                        pass
                    
                    # Determin the other players' positions
                    filtered = utils.filter_color(minimap, OTHER_RANGES)
                    others_count = len(utils.multi_match(filtered, OTHER_TEMPLATE, threshold=0.5))
                    config.map_invaded = others_count > 0

                    # Determin if there is unexpected blackscreen (like dc or something)
                    gray = cv2.cvtColor(self.frame, cv2.COLOR_BGR2GRAY)
                    height, width, _ = self.frame.shape
                    room_change_threshold = 0.9
                    config.blackscreened = np.count_nonzero(gray < 15) / height / width > room_change_threshold

                    # Determin if there is rune buff activated
                    rune_buff = utils.multi_match(self.frame[:self.frame.shape[0] // 8, :],
                                RUNE_BUFF_TEMPLATE,
                                threshold=0.9)
                    if rune_buff:
                        position_in_name = min(rune_buff, key=lambda p: p[0])
                        config.rune_buff_position = (
                            position_in_name[0] + self.window['left'],
                            position_in_name[1] + self.window['top']
                        )
                    else:
                        config.rune_buff_position = None

                    # Determin if there is haiku bot testing activated
                    self.botTestingDetection()
                    if self.haiku_bot_testing_bottomright_position is not None or self.haiku_bot_testing_topleft_position is not None:
                        config.bottesting = True

                    time.sleep(0.05)


    def calibrate(self):
        handle = user32.FindWindowW(None, WINDOW_NAME)
        rect = wintypes.RECT()
        user32.GetWindowRect(handle, ctypes.pointer(rect))
        rect = (rect.left, rect.top, rect.right, rect.bottom)
        rect = tuple(max(0, x) for x in rect)

        self.window['left'] = rect[0]
        self.window['top'] = rect[1]
        self.window['width'] = max(rect[2] - rect[0], MINIMAP_TEMPLATE_WIDTH)
        self.window['height'] = max(rect[3] - rect[1], MINIMAP_TEMPLATE_HEIGHT)

        # Calibrate by finding the top-left and bottom-right corners of the minimap
        # no need to define self.act again cause we already have it
        self.frame = self.screenshot()
        if self.frame is None:
            return
        tl, _ = utils.single_match(self.frame, MINIMAP_TOPLEFT_TEMPLATE)
        _, br = utils.single_match(self.frame, MINIMAP_BOTTOMRIGHT_TEMPLATE)
        self.minimap_topleft_position = (
            tl[0] + MINIMAP_BOTTOM_BORDER,
            tl[1] + MINIMAP_TOP_BORDER
        )
        self.minimap_bottomright_position = (
            max(self.minimap_topleft_position[0] + PLAYERER_TEMPLATE_WIDTH, br[0] - MINIMAP_BOTTOM_BORDER),
            max(self.minimap_topleft_position[1] + PLAYER_TEMPLATE_HEIGHT, br[1] - MINIMAP_BOTTOM_BORDER)
        )
        self.minimap_ratio = (self.minimap_bottomright_position[0] - self.minimap_topleft_position[0]) / (self.minimap_bottomright_position[1] - self.minimap_topleft_position[1])
        self.minimap_sample = self.frame[self.minimap_topleft_position[1]:self.minimap_bottomright_position[1], self.minimap_topleft_position[0]:self.minimap_bottomright_position[0]]
        self.calibrated = True

    def screenshot(self, delay=1):
        try:
            return np.array(self.screenshoter.grab(self.window))
        except mss.exception.ScreenShotError:
            print(f'\n[!] Error while taking screenshot, retrying in {delay} second'
                  + ('s' if delay != 1 else ''))
            time.sleep(delay)

    # needs to be run after calibrate
    def botTestingDetection(self):
        # skip checking if somehow screenshot not success
        if self.frame is None:
            return
        tl, _ = utils.single_match(self.frame, HAIKU_BOT_TESTING_TOPLEFT_TEMPLATE)
        _, br = utils.single_match(self.frame, HAIKU_BOT_TESTING_BOTTOMRIGHT_TEMPLATE)
        self.haiku_bot_testing_topleft_position = (
            tl[0],
            tl[1]
        )
        self.haiku_bot_testing_bottomright_position = (
            br[0],
            br[1]
        )
