import cv2
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk, Image
import src.config as config
import src.utils as utils
import threading
import time

class Displayer():

    def __init__(self):
        self.WIDTH = 400
        self.HEIGHT = 300
        self.window = None
        self.canvas = None
        self.container = None
        self.thread = threading.Thread(target=self._main)
        self.thread.daemon = True
        self.display_thread = threading.Thread(target=self._loop_display)
        self.display_thread.daemon = True
    
    def _main(self):
        self.init_window()
        self.display_thread.start()
        self.window.mainloop()

    def _loop_display(self):
        delay = 1 / 30 # the framerate
        while True:
            self.display_minimap()
            time.sleep(delay)

    def start(self):
        print("Start the minimap display")
        self.thread.start()

    def init_window(self):
        print("start the canvas window")
        self.window = tk.Tk()
        self.window.title('Minimap')
        self.window.geometry("400x500")
        self.window.resizable(False, False)
        self.window.config(menu=self.init_menu(self.window))
        self.init_canvas(self.window)
        

    def init_menu(self, gui):
        menu = tk.Menu(gui)
        function_item = tk.Menu(menu, tearoff=0)
        menu.add_cascade(label="function", menu=function_item)
        def uncalibrate():
            config.capture.calibrated=False
        function_item.add_command(label='Recalibrate', command=uncalibrate)
        return menu
       
    def init_canvas(self, gui):
        self.canvas = tk.Canvas(gui, bg='black',
                                 width=self.WIDTH, height=self.HEIGHT,
                                 borderwidth=0, highlightthickness=0)
        self.canvas.pack(expand=True, fill='both', padx=5, pady=5)


    def display_minimap(self):
        if not config.capture or not config.capture.calibrate or config.minimap is None:
            print("screen no calibrated, skip")
            return
        rune_active = config.rune_active
        rune_position = config.rune_position
        player_pos = config.player_position

        img = cv2.cvtColor(config.minimap, cv2.COLOR_BGR2RGB)
        height, width, _ = img.shape

        # Resize minimap to fit the Canvasg
        ratio = min(self.WIDTH / width, self.HEIGHT / height)
        new_width = int(width * ratio)
        new_height = int(height * ratio)
        if new_height * new_width > 0:
            img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)

        # Draw the player's position on top of everything
        cv2.circle(img,
                    utils.convert_to_absolute(player_pos, img),
                    3,
                    (0, 0, 255),
                    -1)

        # Display the minimap in the Canvas
        img = ImageTk.PhotoImage(Image.fromarray(img))
        if self.container is None:
            self.container = self.canvas.create_image(self.WIDTH // 2,
                                                        self.HEIGHT // 2,
                                                        image=img, anchor=tk.CENTER)
        else:
            self.canvas.itemconfig(self.container, image=img)
        self._img = img                 # Prevent garbage collections