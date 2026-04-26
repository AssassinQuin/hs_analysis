"""Data models for card analysis."""

from analysis.models.card import Card
from analysis.models.game_record import GameRecord

from enum import Enum


class Phase(Enum):
    EARLY = "early"
    MID = "mid"
    LATE = "late"


def detect_phase(turn_number: int) -> Phase:
    if turn_number <= 4:
        return Phase.EARLY
    if turn_number <= 7:
        return Phase.MID
    return Phase.LATE
