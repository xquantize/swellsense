"""Judgements and the hourly score for one spot.

Classifiers describe wind, swell and tide. The rating turns those into a
score, and the report collects a stretch of hours. Nothing here calls a
model or the network.
"""

from swellsense.conditions.rating import HourRating, rate_hour, score_label
from swellsense.conditions.report import ConditionsReport, build_report, rank_spots
from swellsense.conditions.swell import SwellJudgement, classify_swell
from swellsense.conditions.tide import TideJudgement, classify_tide
from swellsense.conditions.wind import WindJudgement, classify_wind

__all__ = [
    "ConditionsReport",
    "HourRating",
    "SwellJudgement",
    "TideJudgement",
    "WindJudgement",
    "build_report",
    "classify_swell",
    "classify_tide",
    "classify_wind",
    "rank_spots",
    "rate_hour",
    "score_label",
]
