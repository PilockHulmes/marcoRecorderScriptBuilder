import cv2
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk, Image
import src.config as config
import src.utils as utils
import threading
import time

# distance that player can activate rune puzzle
DISTANCE_THRESHOLD = 1
#
HORIZONTAL_DISTANCE_THRESHOLD = 1
#
VERTICAL_DISTANCE_THRESHOLD = 1

# distance that player can doublejump to get close to rune
FLASHJUMP_DISTANCE_THRESHOLD = 2_

class Rune():
    
    def __init__(self):
        self.thread =  threading.Thread(target=self._main)
        self.thread.daemon = True
        pass

    def _main(self):
        while True:
            if not config.rune_active:
                time.sleep(1)
                continue
            # TODO: stop the botter firstly
            # start the rune seek loop
            while not self.close_enough():
                # close to rune in the horizontal first
                config.rune_position
                config.player_position
            time.sleep(1)

    def close_enough(self):
        dis = utils.distance(config.rune_position, config.player_position)
        return dis <= DISTANCE_THRESHOLD
