"""Cut-points for the wind, swell and tide classifiers.

They live here so a later pass can tune a boundary without hunting through
the judgement logic. A value sitting on a boundary belongs to the class
named on that constant.
"""

# Degrees away from straight offshore. The boundary stays with the side
# closer to offshore, so 45° is still offshore.
OFFSHORE_MAX_DEG = 45.0  # <= this is offshore
CROSS_OFFSHORE_MAX_DEG = 67.5  # <= this is cross-offshore
CROSS_SHORE_MAX_DEG = 112.5  # <= this is cross-shore
CROSS_ONSHORE_MAX_DEG = 135.0  # <= this is cross-onshore; past it is onshore

# Wind speed in knots. The boundary belongs to the stronger class, so 5 kn
# is light rather than calm.
CALM_MAX_KN = 5.0  # under this is calm
LIGHT_MAX_KN = 10.0  # under this is light
MODERATE_MAX_KN = 15.0  # under this is moderate
STRONG_MAX_KN = 25.0  # under this is strong; at and above is very strong

# A swell aimed this close to the window, but not inside it, is marginal.
SWELL_MARGINAL_DEG = 15.0  # within 15° outside the window

# Swell period in seconds. 8 s is already mixed; 12 s is groundswell.
WINDSWELL_MAX_S = 8.0  # under this is windswell
MIXED_MAX_S = 12.0  # under this is mixed; at and above is groundswell

# Open-ocean swell height in metres, not the height of the breaking wave.
# 0.3 m is small; 2.5 m is big.
FLAT_MAX_M = 0.3  # under this is flat
SMALL_MAX_M = 0.8  # under this is small
FUN_MAX_M = 1.5  # under this is fun
SOLID_MAX_M = 2.5  # under this is solid; at and above is big
