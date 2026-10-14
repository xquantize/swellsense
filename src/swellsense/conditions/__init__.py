"""Pure judgements of wind, swell and tide for one spot.

Scoring these together is a later step. Each function only describes the
aspect it was given.
"""

from swellsense.conditions.swell import SwellJudgement, classify_swell
from swellsense.conditions.tide import TideJudgement, classify_tide
from swellsense.conditions.wind import WindJudgement, classify_wind

__all__ = [
    "SwellJudgement",
    "TideJudgement",
    "WindJudgement",
    "classify_swell",
    "classify_tide",
    "classify_wind",
]
