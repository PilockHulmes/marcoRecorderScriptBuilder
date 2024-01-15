from src.capture import Capture
from src.displayer import Displayer
import src.config as config
import time 


c = Capture()
c.start()

d = Displayer()
d.start()

while True:
    print("Rune active:", config.rune_active)
    print("Rune position:", config.rune_position)
    print("Map Invaded:", config.map_invaded)
    print("Player Position", config.player_position)
    time.sleep(2)