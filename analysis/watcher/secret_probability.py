"""
Opponent secret probability model.

Given opponent class and already-triggered secrets, computes probability
distribution over possible unknown secrets.
"""
from typing import Dict, List, Optional, Tuple

from hearthstone.cardxml import load as load_cardxml
from hearthstone.enums import CardClass, GameTag

# Lazy-loaded secret pool: class_name_lower -> [(card_id, zh_name, trigger_event)]
_SECRET_POOL: Optional[Dict[str, List[Tuple[str, str, str]]]] = None

# Class name mapping
_CLASS_MAP = {
    'hunter': CardClass.HUNTER,
    'mage': CardClass.MAGE,
    'paladin': CardClass.PALADIN,
    'rogue': CardClass.ROGUE,
}


def _load_secret_pool() -> Dict[str, List[Tuple[str, str, str]]]:
    """Load all collectible secrets per class from python-hearthstone."""
    global _SECRET_POOL
    if _SECRET_POOL is not None:
        return _SECRET_POOL

    db, _ = load_cardxml()
    pool: Dict[str, List[Tuple[str, str, str]]] = {}

    for card_id, card in db.items():
        if not card.collectible:
            continue
        if card.tags.get(GameTag.SECRET) != 1:
            continue

        # Get class name
        cls = card.card_class
        # card_class can be a list for dual-class; take first
        if isinstance(cls, list):
            if not cls:
                continue
            cls = cls[0]

        cls_name = cls.name.lower() if hasattr(cls, 'name') else str(cls).lower()

        # Get zhCN name
        strings = card.strings.get(GameTag.CARDNAME, {})
        zh_name = strings.get('zhCN', card.name or card_id)

        # Determine trigger event from card text
        trigger = _infer_trigger_event(card_id, card)

        if cls_name not in pool:
            pool[cls_name] = []
        pool[cls_name].append((card_id, zh_name, trigger))

    _SECRET_POOL = pool
    return _SECRET_POOL


def _infer_trigger_event(card_id: str, card) -> str:
    """Infer secret trigger event from card mechanics tags."""
    # Use GameTag.TRIGGER_SECRETS if available, or infer from mechanics
    # Simplified: use SECRET_DEFS from secret_triggers.py mapping if available
    try:
        from analysis.search.secret_triggers import SECRET_DEFS
        if card_id in SECRET_DEFS:
            return SECRET_DEFS[card_id][0]  # trigger_event
    except ImportError:
        pass

    # Fallback: infer from card text
    text = (card.description or '').lower()
    if '攻击' in text or 'attack' in text or 'minion attacks' in text:
        return 'on_attack'
    if '施放' in text or 'cast' in text or 'spell' in text:
        return 'on_spell_cast'
    if '召唤' in text or 'summon' in text or 'play' in text:
        return 'on_minion_play'
    if '英雄' in text or 'hero' in text:
        return 'on_hero_power'
    return 'unknown'


class SecretProbabilityModel:
    """
    Probability model for opponent's unknown secrets.

    Usage:
        model = SecretProbabilityModel('hunter')
        model.exclude('EX1_610')  # Explosive Trap already triggered
        probs = model.get_probabilities()  # [(card_id, name, prob), ...]
        risk = model.get_attack_risk()     # 0.0-1.0 risk of attacking
    """

    def __init__(self, opponent_class: str):
        self.opponent_class = opponent_class.lower()
        self._excluded: set = set()  # card_ids already triggered/seen
        self._pool = self._get_pool()

    def _get_pool(self) -> List[Tuple[str, str, str]]:
        """Get secret pool for opponent's class."""
        pool = _load_secret_pool()
        return pool.get(self.opponent_class, [])

    def exclude(self, card_id: str) -> None:
        """Exclude a known/triggered secret from the pool."""
        self._excluded.add(card_id)

    def get_probabilities(self) -> List[Tuple[str, str, float]]:
        """Get probability distribution over possible unknown secrets.

        Returns list of (card_id, zh_name, probability), sorted by probability desc.
        Uses uniform prior over remaining pool after exclusions.
        """
        remaining = [(cid, name, trigger) for cid, name, trigger in self._pool
                     if cid not in self._excluded]

        if not remaining:
            return []

        # Uniform prior
        prob = 1.0 / len(remaining)
        result = [(cid, name, prob) for cid, name, _ in remaining]
        result.sort(key=lambda x: x[2], reverse=True)
        return result

    def get_trigger_categories(self) -> Dict[str, float]:
        """Get probability of each trigger category being present.

        Returns dict like {'on_attack': 0.6, 'on_spell_cast': 0.4, ...}
        """
        remaining = [(cid, name, trigger) for cid, name, trigger in self._pool
                     if cid not in self._excluded]

        if not remaining:
            return {}

        # Group by trigger event
        categories: Dict[str, int] = {}
        for _, _, trigger in remaining:
            categories[trigger] = categories.get(trigger, 0) + 1

        total = len(remaining)
        return {cat: count / total for cat, count in categories.items()}

    def get_attack_risk(self) -> float:
        """Risk of triggering a secret when attacking (0.0-1.0)."""
        cats = self.get_trigger_categories()
        # on_attack and on_minion_play are attack-related triggers
        return cats.get('on_attack', 0.0) + cats.get('on_minion_play', 0.0) * 0.5

    def get_spell_risk(self) -> float:
        """Risk of triggering a secret when casting a spell (0.0-1.0)."""
        return self.get_trigger_categories().get('on_spell_cast', 0.0)

    def get_most_likely(self, n: int = 3) -> List[Tuple[str, str, float]]:
        """Top-N most likely secrets."""
        return self.get_probabilities()[:n]

    def get_summary(self) -> str:
        """Human-readable summary for logging."""
        probs = self.get_probabilities()
        if not probs:
            return "无可疑奥秘"

        remaining = len(probs)
        top = probs[:3]
        top_str = ', '.join(f'{name}({prob:.0%})' for _, name, prob in top)
        return f"剩余{remaining}种可能: {top_str}"


def get_secret_pool_for_class(class_name: str) -> List[Tuple[str, str, str]]:
    """Get all possible secrets for a class."""
    pool = _load_secret_pool()
    return pool.get(class_name.lower(), [])


def get_secret_count_for_class(class_name: str) -> int:
    """Get number of possible secrets for a class."""
    return len(get_secret_pool_for_class(class_name))
