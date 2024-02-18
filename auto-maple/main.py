from src.capture import Capture
from src.displayer import Displayer
import src.config as config
import time 
import pydirectinput

c = Capture()
c.start()

d = Displayer()
d.start()

while True:
    # print("Rune active:", config.rune_active)
    # print("Rune position:", config.rune_position)
    # print("Map Invaded:", config.map_invaded)
    # print("Player Position", config.player_position)
    # print("Buff Position", config.rune_buff_position)
    # if config.rune_buff_position:
    #     pydirectinput.moveTo(config.rune_buff_position[0], config.rune_buff_position[1])
    time.sleep(5)