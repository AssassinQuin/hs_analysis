"""
机制共享数据表 — 从 11 个微型 mechanic 模块合并而来。
每个模块仅保留纯数据（dict、list、常量、dataclass），执行逻辑由 engine/dispatch.py 统一处理。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ============================================================
# Herald (兆示) — from herald.py
# ============================================================

HERALD_SOLDIERS = {
    "DEMONHUNTER": {"name": "伊利达雷士兵", "english_name": "Illidari Soldier", "attack": 2, "health": 2},
    "ROGUE": {"name": "暗影刺客", "english_name": "Shadow Assassin", "attack": 2, "health": 1},
    "HUNTER": {"name": "猎手", "english_name": "Huntsman", "attack": 3, "health": 1},
    "MAGE": {"name": "奥术学徒", "english_name": "Arcane Apprentice", "attack": 1, "health": 2},
    "PALADIN": {"name": "白银之手新兵", "english_name": "Silver Hand Recruit", "attack": 2, "health": 2},
    "PRIEST": {"name": "暗影祭司", "english_name": "Shadow Priest", "attack": 1, "health": 3},
    "WARRIOR": {"name": "战歌士兵", "english_name": "Warsong Soldier", "attack": 3, "health": 1},
    "WARLOCK": {"name": "小鬼军团", "english_name": "Imp Legionnaire", "attack": 2, "health": 2},
    "SHAMAN": {"name": "图腾战士", "english_name": "Totem Warrior", "attack": 2, "health": 2},
    "DRUID": {"name": "树人战士", "english_name": "Treant Warrior", "attack": 2, "health": 3},
    "DEATHKNIGHT": {"name": "亡灵士兵", "english_name": "Undead Soldier", "attack": 2, "health": 2},
    "NEUTRAL": {"name": "雇佣兵", "english_name": "Mercenary", "attack": 2, "health": 2},
}


def check_herald(card) -> bool:
    """[从 herald.py 迁移] Check if a card has the Herald mechanic."""
    mechanics = getattr(card, 'mechanics', []) or []
    text = getattr(card, 'text', '') or ''
    eng_text = getattr(card, 'english_text', '') or ''
    return ('兆示' in text or 'herald' in eng_text.lower()
            or 'HERALD' in mechanics)


# ============================================================
# Colossal (巨型) — from colossal.py
# ============================================================

COLOSSAL_APPENDAGES = {
    "DEMONHUNTER": {"name": "末日之翼的附肢", "attack": 2, "health": 2},
    "ROGUE": {"name": "暗影附肢", "attack": 2, "health": 1},
    "HUNTER": {"name": "野兽附肢", "attack": 3, "health": 2},
    "MAGE": {"name": "奥术附肢", "attack": 1, "health": 3},
    "PALADIN": {"name": "圣光附肢", "attack": 2, "health": 3},
    "PRIEST": {"name": "暗影附肢", "attack": 1, "health": 4},
    "WARRIOR": {"name": "战甲附肢", "attack": 3, "health": 1},
    "WARLOCK": {"name": "恶魔附肢", "attack": 2, "health": 2},
    "SHAMAN": {"name": "元素附肢", "attack": 2, "health": 2},
    "DRUID": {"name": "自然附肢", "attack": 2, "health": 2},
    "DEATHKNIGHT": {"name": "亡灵附肢", "attack": 2, "health": 2},
    "NEUTRAL": {"name": "虚空附肢", "attack": 1, "health": 1},
}


def parse_colossal_value(card) -> int:
    """[从 colossal.py 迁移] Parse the colossal appendage count from a card."""
    mechanics = getattr(card, 'mechanics', []) or []
    english_text = getattr(card, 'english_text', '') or ''
    text = getattr(card, 'text', '') or ''

    if 'COLOSSAL' not in mechanics and 'Colossal' not in english_text and '巨型' not in text:
        return 0

    match = re.search(r'Colossal\s*\+\s*(\d+)', english_text)
    if match:
        return int(match.group(1))

    match = re.search(r'巨型\+(\d+)', text)
    if match:
        return int(match.group(1))

    return 1


# ============================================================
# Corrupt (腐蚀) — from corrupt.py
# ============================================================

# corrupt.py 无独立数据表，仅有纯逻辑函数。
# 保留检测函数作为辅助工具迁移。

def has_corrupt(card) -> bool:
    """[从 corrupt.py 迁移] Check if a card has the Corrupt mechanic."""
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    return 'CORRUPT' in mechanics or '腐蚀' in text


# ============================================================
# Rewind (回溯) — from rewind.py
# ============================================================

REWIND_SCORING_BONUS: float = 0.5


def is_rewind_card(card) -> bool:
    """[从 rewind.py 迁移] Check if a card has the Rewind mechanic."""
    mechanics = getattr(card, 'mechanics', None) or []
    text = getattr(card, 'text', '') or ''

    if 'REWIND' in mechanics:
        return True

    if '回溯' in text:
        return True

    return False


# ============================================================
# Rune (符文) — from rune.py
# ============================================================

RUNE_MAP: dict[str, str] = {
    "FROST": "冰霜符文",
    "SHADOW": "邪恶符文",
    "FIRE": "鲜血符文",
}

# Hardcoded rune affiliations for cards that don't have spellSchool
RUNE_LOOKUP: dict[int, str] = {
    # 血液魔术师 (Hematurge) — blood rune discover
    # 畸怪符文剑 (Grotesque Runeblade) — references blood + unholy
    # 死灵殡葬师 (Necrotic Mortician) — unholy rune discover
    # Most minion/weapon rune cards don't have explicit rune fields.
}


def get_rune_type(card: dict) -> str | None:
    """[从 rune.py 迁移] Determine the rune type of a card."""
    school = card.get("spellSchool", "") or ""
    if isinstance(school, str) and school.upper() in RUNE_MAP:
        return RUNE_MAP[school.upper()]

    dbf_id = card.get("dbfId") or card.get("dbf_id")
    if dbf_id is not None:
        try:
            return RUNE_LOOKUP[int(dbf_id)]
        except (KeyError, ValueError, TypeError):
            pass

    return None


def filter_by_rune(pool: list[dict], rune_name: str) -> list[dict]:
    """[从 rune.py 迁移] Filter a discover pool to cards with the given rune type."""
    return [c for c in pool if get_rune_type(c) == rune_name]


def check_last_played_rune(state, rune_name: str) -> bool:
    """[从 rune.py 迁移] Check if the last played card has the given rune type."""
    if state.last_played_card is None:
        return False
    return get_rune_type(state.last_played_card) == rune_name


def parse_rune_discover_target(card_text: str) -> str | None:
    """[从 rune.py 迁移] Parse "发现一张XX符文牌" from card text."""
    if not card_text or not isinstance(card_text, str):
        return None
    for rune_name in RUNE_MAP.values():
        if rune_name in card_text:
            return rune_name
    return None


# ============================================================
# Dark Gift (暗金礼物) — from dark_gift.py
# ============================================================

@dataclass
class DarkGiftEnchantment:
    """[从 dark_gift.py 迁移] A predefined Dark Gift bonus."""
    name: str
    attack_bonus: int = 0
    health_bonus: int = 0
    keyword: str = ""   # WINDFURY, LIFESTEAL, DIVINE_SHIELD, TAUNT, etc.
    effect: str = ""    # Descriptive effect text


DARK_GIFT_ENCHANTMENTS: list[DarkGiftEnchantment] = [
    DarkGiftEnchantment(name="Chaos Power", attack_bonus=2, health_bonus=2),
    DarkGiftEnchantment(name="Shadow Embrace", attack_bonus=1, health_bonus=3),
    DarkGiftEnchantment(name="Frenzy Gift", attack_bonus=3, health_bonus=1),
    DarkGiftEnchantment(name="Wind Gift", keyword="WINDFURY"),
    DarkGiftEnchantment(name="Lifesteal Gift", keyword="LIFESTEAL"),
    DarkGiftEnchantment(name="Divine Shield Gift", keyword="DIVINE_SHIELD"),
    DarkGiftEnchantment(name="Taunt Gift", keyword="TAUNT"),
    DarkGiftEnchantment(name="Rush Gift", keyword="RUSH"),
    DarkGiftEnchantment(name="Deathrattle Damage", effect="deathrattle_damage:2"),
    DarkGiftEnchantment(name="Battlecry Draw", effect="battlecry_draw:1"),
]

# Declarative constraint map — English keyword → mechanics constraint.
_DARK_GIFT_CONSTRAINT_MAP: list[tuple[str, str]] = [
    ("deathrattle", "DEATHRATTLE"),
    ("dragon",      "DRAGON"),
    ("demon",       "DEMON"),
    ("undead",      "UNDEAD"),
    ("elemental",   "ELEMENTAL"),
    ("beast",       "BEAST"),
    ("murloc",      "MURLOC"),
    ("pirate",      "PIRATE"),
    ("mech",        "MECH"),
    ("naga",        "NAGA"),
]


def parse_dark_gift_constraint(english_text: str) -> str:
    """[从 dark_gift.py 迁移] Parse the type constraint from a Dark Gift discover card."""
    en = (english_text or "").lower()
    if "dark gift" not in en:
        return ""
    for keyword, constraint in _DARK_GIFT_CONSTRAINT_MAP:
        if keyword in en:
            return constraint
    return ""


def has_dark_gift_discover(english_text: str) -> bool:
    """[从 dark_gift.py 迁移] Check if card text triggers a Dark Gift discover."""
    return "dark gift" in (english_text or "").lower()


def filter_dark_gift_pool(pool: list[dict], constraint: str = "") -> list[dict]:
    """[从 dark_gift.py 迁移] Filter a discover pool for cards eligible for Dark Gift."""
    if not constraint:
        return pool

    result = []
    for card in pool:
        mechanics = card.get("mechanics", []) or []
        race = card.get("race", "") or ""
        card_type = card.get("type", "") or card.get("card_type", "") or ""

        if constraint == "DEATHRATTLE":
            if "DEATHRATTLE" in mechanics:
                result.append(card)
        elif constraint == "DRAGON":
            if "DRAGON" in race.upper():
                result.append(card)
        elif constraint in mechanics:
            result.append(card)
        elif constraint.upper() in race.upper():
            result.append(card)

    return result


def apply_dark_gift(card: dict, rng_seed: int = 0) -> dict:
    """[从 dark_gift.py 迁移] Apply a random Dark Gift enchantment to a card dict."""
    if not DARK_GIFT_ENCHANTMENTS:
        return card

    from analysis.card.engine.deterministic import DeterministicRNG
    rng = DeterministicRNG(rng_seed)
    gift = rng.choice(DARK_GIFT_ENCHANTMENTS)

    if gift.attack_bonus:
        card["attack"] = card.get("attack", 0) + gift.attack_bonus
    if gift.health_bonus:
        card["health"] = card.get("health", 0) + gift.health_bonus

    if gift.keyword:
        mechanics = card.get("mechanics", [])
        if not isinstance(mechanics, list):
            mechanics = []
        mechanics.append(gift.keyword)
        card["mechanics"] = mechanics

    card["dark_gift"] = gift.name
    return card


def has_dark_gift_in_hand(hand: list) -> bool:
    """[从 dark_gift.py 迁移] Check if any card in hand has been granted Dark Gift."""
    for card in hand:
        if isinstance(card, dict):
            if card.get("dark_gift"):
                return True
            en_text = card.get("english_text", "") or ""
            if "dark gift" in en_text.lower():
                return True
        elif hasattr(card, 'dark_gift') and card.dark_gift:
            return True
        elif hasattr(card, 'english_text'):
            en_text = getattr(card, 'english_text', '') or ''
            if "dark gift" in en_text.lower():
                return True
    return False


# ============================================================
# Dormant (休眠) — from dormant.py
# ============================================================

def parse_dormant_turns(text: str, english_text: str = '') -> int:
    """[从 dormant.py 迁移] Parse dormant turns from card text."""
    if english_text:
        m = re.search(r'Dormant\s*(?:for\s*)?(\d+)', english_text)
        if m:
            return int(m.group(1))
    if text:
        m = re.search(r'休眠\s*(\d+)\s*个?回合', text)
        if m:
            return int(m.group(1))
    if 'Dormant' in english_text or '休眠' in text:
        return 2
    return 0


def is_dormant_card(card) -> bool:
    """[从 dormant.py 迁移] Check if a card has the Dormant mechanic."""
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    english_text = getattr(card, 'english_text', '') or ''
    return 'DORMANT' in mechanics or 'Dormant' in english_text or '休眠' in text


# ============================================================
# Outcast (流放) — from outcast.py
# ============================================================

_OUTCAST_DRAW_EN = re.compile(r'Outcast[：:]\s*Draw\s*(\d+)')
_OUTCAST_DRAW_CN = re.compile(r'流放[：:]\s*再抽(\d+)张')
_OUTCAST_BUFF_EN = re.compile(r'Outcast[：:]\s*\+(\d+)/\+(\d+)')
_OUTCAST_BUFF_CN = re.compile(r'流放[：:]\s*\+(\d+)/\+(\d+)')
_OUTCAST_COST_EN = re.compile(r'Outcast[：:]\s*(?:costs?|Cost)\s*\(?(\d+)\)?')
_OUTCAST_COST_CN = re.compile(r'流放[：:]\s*法力值消耗为[（(]\s*(\d+)\s*[）)]点')


def _parse_outcast_bonus(text: str, english_text: str = '') -> dict:
    """[从 outcast.py 迁移] Parse outcast bonus type and value from card text."""
    m = _OUTCAST_DRAW_EN.search(english_text) or _OUTCAST_DRAW_CN.search(text)
    if m:
        return {"type": "draw", "count": int(m.group(1))}

    m = _OUTCAST_BUFF_EN.search(english_text) or _OUTCAST_BUFF_CN.search(text)
    if m:
        return {"type": "buff", "attack": int(m.group(1)), "health": int(m.group(2))}

    m = _OUTCAST_COST_EN.search(english_text) or _OUTCAST_COST_CN.search(text)
    if m:
        return {"type": "cost", "value": int(m.group(1))}

    if 'Outcast' in english_text or '流放' in text:
        return {"type": "draw", "count": 1}

    return {"type": "draw", "count": 1}


# ============================================================
# Kindred (延系) — from kindred.py
# ============================================================

_KINDRED_RE = re.compile(r'Kindred[：:]?\s*(.+?)(?:<|$)|延系[：:]?\s*(.+?)(?:<|$)', re.DOTALL)
_KINDRED_PRESENT_RE = re.compile(r'Kindred|延系')
_KINDRED_STAT_RE = re.compile(r'[+＋](\d+)/[+＋](\d+)')
_KINDRED_SPELL_DMG_EN = re.compile(r'Spell\s*Damage\s*\+(\d+)', re.IGNORECASE)
_KINDRED_SPELL_DMG_CN = re.compile(r'法术伤害[+＋](\d+)')
_KINDRED_COST_RED_EN = re.compile(r'(?:Cost|cost)\s*(?:reduced?)?\s*(?:by\s*)?\(?(\d+)\)?')
_KINDRED_COST_RED_CN = re.compile(r'消耗减少[（(]\s*(\d+)\s*[）)]')


def _card_attr(card, key: str, default=None):
    """[从 kindred.py 迁移] Safe attribute accessor for dict or object cards."""
    if isinstance(card, dict):
        return card.get(key, default)
    return getattr(card, key, default)


def has_kindred(card_text: str) -> bool:
    """[从 kindred.py 迁移] Check if card text contains 延系 keyword."""
    return bool(_KINDRED_PRESENT_RE.search(card_text or ""))


def parse_kindred_bonus(card_text: str, english_text: str = '') -> str | None:
    """[从 kindred.py 迁移] Extract the bonus effect text after Kindred: or 延系：."""
    en_clean = re.sub(r'<[^>]+>', ' ', english_text or "")
    cn_clean = re.sub(r'<[^>]+>', ' ', card_text or "")
    m = re.search(r'Kindred[：:]?\s*(.+?)(?:\n|$)', en_clean, re.IGNORECASE)
    if not m:
        m = re.search(r'延系[：:]?\s*(.+?)(?:\n|$)', cn_clean)
    if m:
        return m.group(1).strip()
    return None


def check_kindred_active(state, card) -> bool:
    """[从 kindred.py 迁移] Check if card's race/spellSchool overlaps with last turn's plays."""
    race_str = _card_attr(card, "race", "") or ""
    if isinstance(race_str, str):
        card_races = {r.upper() for r in race_str.split() if r}
    else:
        card_races = set()

    if card_races & state.last_turn_races:
        return True

    school = _card_attr(card, "spellSchool", "") or _card_attr(card, "spell_school", "") or ""
    if isinstance(school, str) and school:
        card_schools = {s.upper() for s in school.split() if s}
        if card_schools & state.last_turn_schools:
            return True

    return False


# ============================================================
# Corpse (残骸) — from corpse.py
# ============================================================

_CORPSE_SPEND_RE = re.compile(
    r"Spend\s*(\d+)\s*Corpse(?:s)?|Spend\s*up\s*to\s*(\d+)\s*Corpse(?:s)?"
    r"|消耗最多\s*(\d+)\s*份\s*残骸|消耗\s*(\d+)\s*份\s*残骸"
)
_CORPSE_GAIN_RE = re.compile(
    r"Gain\s*(?:a\s+)?(?:(\d+)\s+)?Corpse(?:s)?|获得\s*(?:一份|(\d+)\s*份)\s*残骸"
)

# 法瑞克 (Falric) — "你获得的残骸量为正常的两倍"
_FALRIC_NAME = "法瑞克"


@dataclass
class CorpseEffect:
    """[从 corpse.py 迁移] A parsed corpse cost + effect pair from card text."""
    cost: int
    is_optional: bool
    effect_text: str


def parse_corpse_effects(card_text: str) -> list[CorpseEffect]:
    """[从 corpse.py 迁移] Parse corpse spend requirements from card text."""
    if not card_text:
        return []

    effects: list[CorpseEffect] = []
    text = card_text or ""

    for m in _CORPSE_SPEND_RE.finditer(text):
        spend_exact = m.group(1)
        spend_up_to = m.group(2)
        cn_max_cost = m.group(3)
        cn_exact_cost = m.group(4)

        if spend_up_to or cn_max_cost:
            cost = int(spend_up_to or cn_max_cost)
            effects.append(CorpseEffect(
                cost=cost,
                is_optional=True,
                effect_text=text[m.end():].strip()[:80],
            ))
        elif spend_exact or cn_exact_cost:
            cost = int(spend_exact or cn_exact_cost)
            effects.append(CorpseEffect(
                cost=cost,
                is_optional=False,
                effect_text=text[m.end():].strip()[:80],
            ))

    return effects


def parse_corpse_gain(card_text: str) -> int:
    """[从 corpse.py 迁移] Parse corpse gain amount from card text."""
    if not card_text:
        return 0

    m = _CORPSE_GAIN_RE.search(card_text)
    if m:
        val = m.group(1) or m.group(2)
        return int(val) if val else 1

    return 0


def can_afford_corpses(state, cost: int) -> bool:
    """[从 corpse.py 迁移] Check if player has enough corpses."""
    return state.corpses >= cost


def has_double_corpse_gen(state) -> bool:
    """[从 corpse.py 迁移] Check if 法瑞克 (Falric) is on the friendly board."""
    for m in state.board:
        card_ref = getattr(m, 'card_ref', None)
        if card_ref:
            en_text = getattr(card_ref, 'english_text', '') or ''
            if 'corpse' in en_text.lower() and 'twice' in en_text.lower():
                return True
        if _FALRIC_NAME in (m.name or ""):
            return True
    return False


# ============================================================
# Imbue (灌注) — from imbue.py
# ============================================================

IMBUE_HERO_POWERS = {
    "DRUID": {
        "effect": "summon",
        "base_attack": 1,
        "base_health": 1,
        "scaling": True,
        "text": "召唤一个{imbue_level}/{imbue_level}的树人",
    },
    "HUNTER": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
        "text": "造成{1 + imbue_level}点伤害",
    },
    "MAGE": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
        "text": "造成{1 + imbue_level}点伤害",
    },
    "PALADIN": {
        "effect": "summon",
        "base_attack": 1,
        "base_health": 1,
        "scaling": True,
        "text": "召唤一个{1+imbue_level}/{1+imbue_level}的报告兵",
    },
    "PRIEST": {
        "effect": "heal",
        "base_heal": 2,
        "scaling": True,
        "text": "恢复{2 + imbue_level}点生命",
    },
    "ROGUE": {
        "effect": "weapon",
        "base_attack": 1,
        "base_durability": 2,
        "scaling": True,
        "text": "装备一把{1+imbue_level}/2的匕首",
    },
    "SHAMAN": {
        "effect": "random_totem",
        "base_text": "随机召唤一个图腾",
    },
    "WARLOCK": {
        "effect": "damage_self_draw",
        "base_damage": 2,
        "base_draw": 1,
        "text": "造成{2}点伤害，抽{1}张牌",
    },
    "WARRIOR": {
        "effect": "armor",
        "base_armor": 2,
        "scaling": True,
        "text": "获得{2 + imbue_level}点护甲",
    },
    "DEMONHUNTER": {
        "effect": "damage",
        "base_damage": 1,
        "scaling": True,
        "text": "造成{1+imbue_level}点伤害",
    },
    "DEATHKNIGHT": {
        "effect": "armor",
        "base_armor": 2,
        "scaling": True,
        "text": "获得{2+imbue_level}点护甲",
    },
}
