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

# Hourly score. rating.py applies these in order: swell size and kind, then
# wind, then tide, then the swell window. Flat swell is a hard zero and does
# not take the other adjustments. Parts that would leave 0..10 are cut back
# so they still add up to the score.

# Open-ocean size, before the period adjustment. Flat is handled on its own.
SWELL_SIZE_BASE: dict[str, int] = {
    "flat": 0,
    "small": 3,
    "fun": 5,
    "solid": 6,
    "big": 6,  # same base as solid; size is not a safety judgement
}

# Added to the size base. A short-period sea is worth less than a groundswell.
SWELL_KIND_ADJUST: dict[str, int] = {
    "windswell": -2,
    "mixed": 0,
    "groundswell": 1,
}

# Wind quality from the wind classifier. Cross-shore is the zero.
# Glassy is calm air, so it does not also receive the offshore bonus.
# Cross-offshore sits between offshore and cross-shore.
WIND_QUALITY_ADJUST: dict[str, int] = {
    "glassy": 2,
    "offshore": 2,
    "cross-offshore": 1,
    "cross-shore": 0,
    "cross-onshore": -2,
    "onshore": -3,
}

# Taken off an offshore or cross-offshore bonus. The bonus stays at zero
# rather than becoming a penalty. Glassy is calm, so these cuts do not apply.
OFFSHORE_BONUS_CUT: dict[str, int] = {
    "calm": 0,
    "light": 0,
    "moderate": 0,
    "strong": 1,
    "very strong": 2,
}

# A swell just outside the window loses this many points.
MARGINAL_WINDOW_PENALTY = 1
# A swell well outside the window cannot score above this.
OUTSIDE_WINDOW_CAP = 2

# Applied only when the tide judgement is certain. Uncertain adds nothing.
TIDE_SUITS_BONUS = 1
TIDE_MISMATCH_PENALTY = 1

# The published score stays inside this range.
SCORE_MIN = 0
SCORE_MAX = 10

# Labels. A score on the boundary takes the higher label, so 3 is fair.
FAIR_MIN = 3  # under this is poor
GOOD_MIN = 5  # under this is fair
GREAT_MIN = 7  # under this is good
EPIC_MIN = 9  # under this is great; at and above is epic
