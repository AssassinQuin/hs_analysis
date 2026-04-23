# mechanics package — Mechanic protocol adapters
#
# Each module wraps an existing mechanic (corpse, kindred, quest, etc.)
# to implement the Mechanic protocol from analysis.search.mechanic.

from analysis.search.mechanics.corpse_mechanic import CorpseMechanic
from analysis.search.mechanics.kindred_mechanic import KindredMechanic
from analysis.search.mechanics.quest_mechanic import QuestMechanic
from analysis.search.mechanics.herald_mechanic import HeraldMechanic
from analysis.search.mechanics.imbue_mechanic import ImbueMechanic

__all__ = [
    "CorpseMechanic",
    "KindredMechanic",
    "QuestMechanic",
    "HeraldMechanic",
    "ImbueMechanic",
]
