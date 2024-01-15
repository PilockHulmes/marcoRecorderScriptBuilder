
#################################
#       Global Variables        #
#################################
# The player's position relative to the minimap
player_position = (0, 0)
# The rune's position relative to the minimap
rune_position = (0, 0)
rune_active = False
# If the map has other players
map_invaded = False
# If there is blackscree
blackscreened = False
# The image of minimap
minimap = None


#############################
#       Shared Modules      #
#############################
# Shares the video capture loop
capture = None