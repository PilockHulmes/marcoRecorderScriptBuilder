
#################################
#       Global Variables        #
#################################
# The player's position relative to the minimap
player_position = (0, 0)
# The rune's position relative to the minimap
rune_position = (0, 0)
rune_active = False
rune_solved = False
# The rune buff's position, used to cancel buff
rune_buff_position = None
# If the map has other players
map_invaded = False
# If there is blackscree
blackscreened = False
# The image of minimap
minimap = None
# If bot testing happened
bottesting = False

#############################
#       Shared Modules      #
#############################
# Shares the video capture loop
capture = None