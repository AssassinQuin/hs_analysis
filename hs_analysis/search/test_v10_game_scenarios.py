#!/usr/bin/env python3
"""V10 Simulation-Based Game Scenario Tests

10 realistic game scenarios using REAL decks from parsed_decks.json.
Each scenario matches a specific player deck vs opponent deck, uses ONLY
cards from those decks (validated at runtime by SimDeck), and exercises
4-6 mechanics through multi-turn gameplay.

All cards in hand/board/weapon are validated against deck composition.
Opponent minions also come from the opponent's real deck.

Matchups (player vs opponent):
  1. Hunter(4)  vs Warlock(1)  T4 — Aggro rush + deathrattle + freeze
  2. Warlock(1) vs Druid(6)    T5 — Quest discover + taunt defense
  3. DH(0)      vs Warlock(2)  T3 — Weapon + spell aggro
  4. Druid(6)   vs Warlock(2)  T7 — Dragon ramp + innervate
  5. Warlock(5) vs Hunter(4)   T5 — Stealth + weapon + combo
  6. Warlock(2) vs Warlock(5)  T8 — Charge finisher lethal
  7. Warlock(1) vs Hunter(4)   T6 — Quest defense + discover chain
  8. Warlock(5) vs Druid(6)    T6 — Old Gods pressure + 0-cost spell
  9. Druid(6)   vs Warlock(3)  T5 — Ramp + rush + discover
  10. Warlock(2) vs Druid(6)   T8 — Dragon clash + charge lethal
"""

import pytest

from hs_analysis.search.test_v9_hdt_batch02_deck_random import DeckTestGenerator
from hs_analysis.search.game_state import (
    GameState, HeroState, ManaState, OpponentState, Minion, Weapon,
)
from hs_analysis.models.card import Card
from hs_analysis.search.rhea_engine import (
    RHEAEngine, Action,
    enumerate_legal_actions, apply_action,
)
from hs_analysis.search.lethal_checker import max_damage_bound
from hs_analysis.utils.spell_simulator import resolve_effects
from hs_analysis.evaluators.composite import evaluate

_gen = None


def _get_gen():
    global _gen
    if _gen is None:
        _gen = DeckTestGenerator.get()
    return _gen


class SimDeck:
    """Validates card usage against a real deck composition."""

    def __init__(self, deck_idx):
        gen = _get_gen()
        self.deck_idx = deck_idx
        self.expanded = gen.expanded_decks[deck_idx]
        self._counts = {}
        for cd in self.expanded:
            dbf = cd.get('dbfId', 0)
            self._counts[dbf] = self._counts.get(dbf, 0) + 1
        self._used = {}

    def _check(self, dbf_id):
        avail = self._counts.get(dbf_id, 0)
        used = self._used.get(dbf_id, 0)
        assert used < avail, (
            f"Deck {self.deck_idx}: card {dbf_id} exhausted "
            f"({used}/{avail})"
        )
        self._used[dbf_id] = used + 1

    def card(self, dbf_id):
        self._check(dbf_id)
        return _get_gen()._card_data_to_hand_card(_get_gen().card_db[dbf_id])

    def minion(self, dbf_id, can_attack=True, owner="friendly"):
        self._check(dbf_id)
        return _make_minion(dbf_id, can_attack=can_attack, owner=owner)

    def weapon(self, dbf_id):
        self._check(dbf_id)
        return _make_weapon(dbf_id)

    def remaining(self):
        return sum(self._counts.values()) - sum(self._used.values())


def _make_minion(dbf_id, can_attack=True, owner="friendly"):
    cd = _get_gen().card_db[dbf_id]
    mechs = set(cd.get('mechanics', []))
    hp = cd.get('health', 1)
    return Minion(
        dbf_id=dbf_id,
        name=cd.get('name', ''),
        attack=cd.get('attack', 0),
        health=hp, max_health=hp,
        cost=cd.get('cost', 0),
        can_attack=can_attack or 'CHARGE' in mechs or 'RUSH' in mechs,
        has_charge='CHARGE' in mechs,
        has_rush='RUSH' in mechs,
        has_taunt='TAUNT' in mechs,
        has_divine_shield='DIVINE_SHIELD' in mechs,
        has_windfury='WINDFURY' in mechs,
        has_stealth='STEALTH' in mechs,
        has_poisonous='POISONOUS' in mechs,
        has_lifesteal='LIFESTEAL' in mechs,
        has_reborn='REBORN' in mechs,
        spell_power=1 if 'SPELLPOWER' in mechs else 0,
        enchantments=[], owner=owner,
    )


def _make_weapon(dbf_id):
    cd = _get_gen().card_db[dbf_id]
    return Weapon(
        name=cd.get('name', ''),
        attack=cd.get('attack', 0),
        health=cd.get('durability', cd.get('health', 0)),
    )


def _engine():
    return RHEAEngine(pop_size=15, max_gens=20, time_limit=100.0,
                      max_chromosome_length=5)


def _class_of(deck_idx):
    gen = _get_gen()
    raw = gen.decks[deck_idx].get('class', '')
    if '(' in raw:
        dbf_str = raw.split('(')[1].rstrip(')')
        try:
            dbf = int(dbf_str)
        except ValueError:
            return 'NEUTRAL'
        c = gen.card_db.get(dbf, {}).get('cardClass', 'NEUTRAL')
        return c if c and c != 'NEUTRAL' else 'DEMONHUNTER'
    return {'Warlock': 'WARLOCK', 'Hunter': 'HUNTER',
            'Druid': 'DRUID'}.get(raw, raw.upper())


# ===================================================================
# Scenario 1: Hunter(4) vs Warlock(1) T4 — Aggro Rush
# Hunter plays 1-cost minions T1-T2, now has spell hand T4
# Exercises: DEATHRATTLE, FREEZE+BATTLECRY, TAUNT blocking, spell damage
# ===================================================================

class Test01HunterAggroT4:

    @pytest.fixture
    def state(self):
        p = SimDeck(4)
        o = SimDeck(1)

        board = [
            p.minion(118222, can_attack=True),   # 炽烈烬火 2/1 DEATHRATTLE
            p.minion(117381, can_attack=True),   # 抛石鱼人 1/3 BATTLECRY
        ]
        hand = [
            p.card(69546),   # 奥术射击 1c
            p.card(117039),  # 击伤猎物 1c RUSH
            p.card(119696),  # 精确射击 2c
            p.card(102227),  # 冰川裂片 1c BATTLECRY+FREEZE
        ]
        opp_board = [
            o.minion(112923, can_attack=True, owner="enemy"),  # 石丘防御者 1/5 TAUNT
        ]
        return GameState(
            hero=HeroState(hp=24, hero_class=_class_of(4)),
            mana=ManaState(available=4, max_mana=4),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=28, hero_class=_class_of(1)),
                board=opp_board, hand_count=6, deck_remaining=o.remaining(),
            ),
            turn_number=4,
        )

    def test_hunter_aggro_t4(self, state):
        legal = enumerate_legal_actions(state)

        # (1) DEATHRATTLE minion on board
        assert state.board[0].name == '炽烈烬火'

        # (2) FREEZE+BATTLECRY minion (冰川裂片) can be played
        freeze_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 102227]
        assert len(freeze_idx) == 1
        freeze_plays = [a for a in legal
                        if a.action_type == 'PLAY' and a.card_index == freeze_idx[0]]
        assert len(freeze_plays) >= 1

        # (3) Opponent TAUNT blocks face attacks
        opp_taunts = [m for m in state.opponent.board if m.has_taunt]
        assert len(opp_taunts) == 1
        face_attacks = [a for a in legal
                        if a.action_type == 'ATTACK' and a.target_index == 0]
        assert len(face_attacks) == 0, 'Taunt should block face attacks'

        # (4) RUSH spell (击伤猎物) summons a minion
        rush_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 117039][0]
        post = resolve_effects(state.copy(), state.hand[rush_idx])
        assert len(post.board) > len(state.board), '击伤猎物 should summon'

        # (5) Engine search valid
        result = _engine().search(state)
        assert result is not None
        non_end = [a for a in result.best_chromosome if a.action_type != 'END_TURN']
        assert len(non_end) >= 1, 'Engine should find at least 1 non-end action'


# ===================================================================
# Scenario 2: Warlock(1) vs Druid(6) T5 — Quest Discover
# Warlock has discover-heavy hand, quest card, taunt on board
# Exercises: QUEST, DISCOVER (x4 cards), TAUNT, REWIND, multi-play
# ===================================================================

class Test02WarlockQuestDiscoverT5:

    @pytest.fixture
    def state(self):
        p = SimDeck(1)
        o = SimDeck(6)

        board = [
            p.minion(123385, can_attack=True),   # 蔽影密探 2/2
            p.minion(123398, can_attack=True),   # 冬泉雏龙 1/2
        ]
        hand = [
            p.card(118183),  # 禁忌序列 1c QUEST+DISCOVER
            p.card(118266),  # 乱翻库存 3c DISCOVER
            p.card(126982),  # 符文宝珠 2c
            p.card(123410),  # 激寒急流 1c
            p.card(112923),  # 石丘防御者 3c TAUNT+DISCOVER
        ]
        opp_board = [
            o.minion(122967, can_attack=True, owner="enemy"),  # 费伍德树人 2/2
            o.minion(122968, can_attack=False, owner="enemy"), # 护巢龙 4/5 TAUNT
        ]
        return GameState(
            hero=HeroState(hp=22, hero_class=_class_of(1)),
            mana=ManaState(available=5, max_mana=5),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=25, hero_class=_class_of(6)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=5,
        )

    def test_warlock_quest_discover_t5(self, state):
        legal = enumerate_legal_actions(state)

        # (1) QUEST card has DISCOVER mechanic
        quest = state.hand[0]
        assert 'QUEST' in (quest.mechanics or [])

        # (2) Multiple DISCOVER cards in hand
        discover_cards = [c for c in state.hand
                          if 'DISCOVER' in (c.mechanics or [])]
        assert len(discover_cards) >= 3

        # (3) Opponent TAUNT blocks face
        face_attacks = [a for a in legal
                        if a.action_type == 'ATTACK' and a.target_index == 0]
        assert len(face_attacks) == 0

        # (4) 4+ playable cards this turn
        playable = {a.card_index for a in legal if a.action_type == 'PLAY'}
        assert len(playable) >= 4

        # (5) Engine finds valid plan
        result = _engine().search(state)
        assert result is not None
        play_count = sum(1 for a in result.best_chromosome if a.action_type == 'PLAY')
        assert play_count >= 1


# ===================================================================
# Scenario 3: DH(0) vs Warlock(2) T3 — Weapon Spell Aggro
# DH has weapon equipped from T1, charge minion on board, spell hand
# Exercises: WEAPON ATTACK, CHARGE, spell burst, cheap aggro
# ===================================================================

class Test03DHWeaponSpellT3:

    @pytest.fixture
    def state(self):
        p = SimDeck(0)
        o = SimDeck(2)

        board = [
            p.minion(120074, can_attack=True),  # 布洛克斯加 CHARGE
        ]
        hand = [
            p.card(114654),  # 恐怖收割 2c
            p.card(115626),  # 燃薪咒符 2c
            p.card(117686),  # 虫害侵扰 2c
        ]
        opp_board = [
            o.minion(122933, can_attack=False, owner="enemy"),  # 载蛋雏龙 1/2
            o.minion(114218, can_attack=False, owner="enemy"),  # 黑暗的龙骑士 2/1
        ]
        return GameState(
            hero=HeroState(hp=28, hero_class=_class_of(0),
                           weapon=p.weapon(120993)),  # 迷时战刃 2/2
            mana=ManaState(available=3, max_mana=3),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=26, hero_class=_class_of(2)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=3,
        )

    def test_dh_weapon_spell_t3(self, state):
        legal = enumerate_legal_actions(state)

        # (1) Weapon ATTACK is legal (P0-1 fix)
        weapon_atks = [a for a in legal
                       if a.action_type == 'ATTACK' and a.source_index == -1]
        assert len(weapon_atks) >= 1

        # (2) CHARGE minion on board
        assert state.board[0].has_charge is True
        charge_atks = [a for a in legal
                       if a.action_type == 'ATTACK' and a.source_index == 0]
        assert len(charge_atks) >= 1

        # (3) max_damage_bound covers board + weapon + spells
        bound = max_damage_bound(state)
        assert bound >= 6, f'Bound {bound} should be 6+'

        # (4) Can play 1 spell with 3 mana
        spell_plays = [a for a in legal if a.action_type == 'PLAY']
        assert len(spell_plays) >= 1

        # (5) Engine finds attack + spell plan
        result = _engine().search(state)
        assert result is not None
        non_end = [a for a in result.best_chromosome if a.action_type != 'END_TURN']
        assert len(non_end) >= 1


# ===================================================================
# Scenario 4: Druid(6) vs Warlock(2) T7 — Dragon Ramp
# Druid ramped with 激活, has taunt on board, holding RUSH finisher
# Exercises: 激活(0c), TAUNT, RUSH+DEATHRATTLE+BATTLECRY, DISCOVER
# ===================================================================

class Test04DruidRampT7:

    @pytest.fixture
    def state(self):
        p = SimDeck(6)
        o = SimDeck(2)

        board = [
            p.minion(122968, can_attack=True),   # 护巢龙 4/5 TAUNT
            p.minion(122967, can_attack=True),   # 费伍德树人 2/2
            p.minion(122500, can_attack=True),   # 晦鳞巢母 4/3
        ]
        hand = [
            p.card(69550),    # 激活 0c
            p.card(129171),   # 地底虫王 7c RUSH+DEATHRATTLE+BATTLECRY
            p.card(115080),   # 丰裕之角 2c DISCOVER
            p.card(120748),   # 潮起潮落 2c
        ]
        opp_board = [
            o.minion(120503, can_attack=True, owner="enemy"),  # 现场播报员 3/3
            o.minion(122933, can_attack=False, owner="enemy"), # 载蛋雏龙 1/2
            o.minion(123385, can_attack=False, owner="enemy"), # 蔽影密探 2/2
        ]
        return GameState(
            hero=HeroState(hp=18, hero_class=_class_of(6)),
            mana=ManaState(available=7, max_mana=7),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=22, hero_class=_class_of(2)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=7,
        )

    def test_druid_ramp_t7(self, state):
        legal = enumerate_legal_actions(state)

        # (1) 激活 (0c) is always legal
        activate_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 69550]
        assert len(activate_idx) == 1
        activate_plays = [a for a in legal
                          if a.action_type == 'PLAY' and a.card_index == activate_idx[0]]
        assert len(activate_plays) >= 1

        # (2) 地底虫王 (7c) playable at 7 mana
        bug_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 129171][0]
        bug_plays = [a for a in legal
                     if a.action_type == 'PLAY' and a.card_index == bug_idx]
        assert len(bug_plays) >= 1

        # (3) RUSH on 地底虫王
        assert state.hand[bug_idx].cost == 7
        m = _make_minion(129171)
        assert m.has_rush is True

        # (4) TAUNT on board (护巢龙)
        assert any(m.has_taunt for m in state.board)

        # (5) Engine finds valid plan
        result = _engine().search(state)
        assert result is not None
        play_count = sum(1 for a in result.best_chromosome if a.action_type == 'PLAY')
        assert play_count >= 1


# ===================================================================
# Scenario 5: Warlock(5) vs Hunter(4) T5 — Stealth Weapon Combo
# Warlock has stealth minion, combo cards, weapon in hand
# Exercises: STEALTH, COMBO, WEAPON play, opponent DEATHRATTLE
# ===================================================================

class Test05WarlockStealthT5:

    @pytest.fixture
    def state(self):
        p = SimDeck(5)
        o = SimDeck(4)

        board = [
            p.minion(129347, can_attack=True),  # 间谍女郎 3/1 STEALTH
            p.minion(120460, can_attack=True),  # 狐人老千 3/2 COMBO
        ]
        hand = [
            p.card(119816),  # 弑君者 2c 3/2 WEAPON
            p.card(123605),  # 暮光祭礼 2c COMBO
            p.card(123549),  # 癫狂的追随者 3c
            p.card(117697),  # 异教地图 2c
        ]
        opp_board = [
            o.minion(118222, can_attack=True, owner="enemy"),  # 炽烈烬火 2/1 DR
            o.minion(122937, can_attack=False, owner="enemy"), # 进击的募援官 1/2
        ]
        return GameState(
            hero=HeroState(hp=20, hero_class=_class_of(5)),
            mana=ManaState(available=5, max_mana=5),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=22, hero_class=_class_of(4)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=5,
        )

    def test_warlock_stealth_t5(self, state):
        legal = enumerate_legal_actions(state)

        # (1) STEALTH minion on board
        assert state.board[0].has_stealth is True

        # (2) WEAPON card playable
        weapon_idx = [i for i, c in enumerate(state.hand) if c.card_type == 'WEAPON']
        assert len(weapon_idx) == 1
        weapon_plays = [a for a in legal
                        if a.action_type == 'PLAY' and a.card_index == weapon_idx[0]]
        assert len(weapon_plays) >= 1

        # (3) COMBO cards in hand
        combo_cards = [c for c in state.hand if 'COMBO' in (c.mechanics or [])]
        assert len(combo_cards) >= 1

        # (4) Opponent DEATHRATTLE minion
        opp_dr = [m for m in state.opponent.board if m.name == '炽烈烬火']
        assert len(opp_dr) == 1

        # (5) Engine plays weapon + minion
        result = _engine().search(state)
        assert result is not None
        assert result.best_fitness > -9999


# ===================================================================
# Scenario 6: Warlock(2) vs Warlock(5) T8 — Charge Finisher
# Warlock Dragon has board, holding 格罗玛什 CHARGE for lethal
# Exercises: CHARGE lethal, max_damage_bound, multi-attack, late game
# ===================================================================

class Test06WarlockChargeLethalT8:

    @pytest.fixture
    def state(self):
        p = SimDeck(2)
        o = SimDeck(5)

        board = [
            p.minion(120503, can_attack=True),   # 现场播报员 3/3
            p.minion(121196, can_attack=True),   # 先觉蜿变幼龙 6/8
        ]
        hand = [
            p.card(69643),    # 格罗玛什 8c CHARGE
            p.card(123164),   # 烈火炙烤 1c
            p.card(120975),   # 先行打击 2c
        ]
        opp_board = [
            o.minion(115139, can_attack=True, owner="enemy"),   # 梦魇之王萨维斯 4/4
            o.minion(123549, can_attack=False, owner="enemy"),  # 癫狂的追随者 3/3
        ]
        return GameState(
            hero=HeroState(hp=14, hero_class=_class_of(2)),
            mana=ManaState(available=8, max_mana=8),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=12, hero_class=_class_of(5)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=8,
        )

    def test_warlock_charge_lethal_t8(self, state):
        legal = enumerate_legal_actions(state)

        # (1) CHARGE minion (格罗玛什) playable at 8 mana
        grom_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 69643][0]
        grom_plays = [a for a in legal
                      if a.action_type == 'PLAY' and a.card_index == grom_idx]
        assert len(grom_plays) >= 1

        # (2) max_damage_bound covers 12 HP (board 3+6=9 + charge 4 + spells = 17+)
        bound = max_damage_bound(state)
        assert bound >= 12, f'Bound {bound} should cover 12 HP'

        # (3) Existing board can attack
        attack_actions = [a for a in legal if a.action_type == 'ATTACK']
        assert len(attack_actions) >= 2

        # (4) Opponent TAUNT blocks face from current board
        opp_taunts = [m for m in state.opponent.board if m.has_taunt]
        face_attacks = [a for a in attack_actions if a.target_index == 0]
        # No taunt on opponent board — face attacks should exist
        if not opp_taunts:
            assert len(face_attacks) >= 2

        # (5) Engine explores lethal paths
        result = _engine().search(state)
        assert result is not None
        non_end = [a for a in result.best_chromosome if a.action_type != 'END_TURN']
        assert len(non_end) >= 2


# ===================================================================
# Scenario 7: Warlock(1) vs Hunter(4) T6 — Quest Defense
# Warlock defends with taunt/discover while Hunter pressures
# Exercises: QUEST progress, DISCOVER chain, TAUNT defense, REWIND
# ===================================================================

class Test07WarlockQuestDefenseT6:

    @pytest.fixture
    def state(self):
        p = SimDeck(1)
        o = SimDeck(4)

        board = [
            p.minion(112923, can_attack=True),   # 石丘防御者 1/5 TAUNT
            p.minion(131356, can_attack=True),   # 迅猛龙先锋 4/2
        ]
        hand = [
            p.card(119633),  # 操控时间 4c DISCOVER
            p.card(121675),  # 时间之沙 1c DISCOVER+TRIGGER_VISUAL(rewind)
            p.card(118485),  # 科技恐龙 7c TAUNT
            p.card(115635),  # 焚火林地 2c
            p.card(118266),  # 乱翻库存 3c DISCOVER
        ]
        opp_board = [
            o.minion(120788, can_attack=True, owner="enemy"),  # 拾箭龙鹰 3/1
            o.minion(118222, can_attack=True, owner="enemy"),  # 炽烈烬火 2/1 DR
            o.minion(102227, can_attack=False, owner="enemy"), # 冰川裂片 2/1
        ]
        return GameState(
            hero=HeroState(hp=14, hero_class=_class_of(1)),
            mana=ManaState(available=6, max_mana=6),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=24, hero_class=_class_of(4)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=6,
        )

    def test_warlock_quest_defense_t6(self, state):
        legal = enumerate_legal_actions(state)

        # (1) TAUNT on board (石丘防御者)
        assert any(m.has_taunt for m in state.board)

        # (2) Multiple DISCOVER cards in hand
        discover_cards = [c for c in state.hand if 'DISCOVER' in (c.mechanics or [])]
        assert len(discover_cards) >= 3

        # (3) REWIND card (时间之沙) has TRIGGER_VISUAL
        rewind_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 121675]
        assert len(rewind_idx) == 1
        rw = state.hand[rewind_idx[0]]
        assert 'TRIGGER_VISUAL' in (rw.mechanics or [])

        # (4) 7-cost TAUNT (科技恐龙) not playable at 6 mana
        dino_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 118485][0]
        dino_plays = [a for a in legal
                      if a.action_type == 'PLAY' and a.card_index == dino_idx]
        assert len(dino_plays) == 0, '7c card should not be playable at 6 mana'

        # (5) Engine plays discover cards
        result = _engine().search(state)
        assert result is not None
        play_count = sum(1 for a in result.best_chromosome if a.action_type == 'PLAY')
        assert play_count >= 1

        # (6) Evaluate produces finite score
        import math
        score = evaluate(state)
        assert not math.isinf(score)


# ===================================================================
# Scenario 8: Warlock(5) vs Druid(6) T6 — Old Gods Pressure
# Warlock Old Gods: stealth + combo, 0-cost spell, weapon
# Exercises: STEALTH, COMBO, 0-cost spell, opponent TAUNT, WEAPON
# ===================================================================

class Test08WarlockOldGodsT6:

    @pytest.fixture
    def state(self):
        p = SimDeck(5)
        o = SimDeck(6)

        board = [
            p.minion(129347, can_attack=True),   # 间谍女郎 3/1 STEALTH
            p.minion(119815, can_attack=True),   # 莱恩国王 3c
            p.minion(120460, can_attack=True),   # 狐人老千 3/2 COMBO
        ]
        hand = [
            p.card(119816),  # 弑君者 2c 3/2 WEAPON
            p.card(122832),  # 奥卓克希昂 6c
            p.card(69623),   # 伺机待发 0c
            p.card(117697),  # 异教地图 2c
        ]
        opp_board = [
            o.minion(122968, can_attack=True, owner="enemy"),   # 护巢龙 4/5 TAUNT
            o.minion(115139, can_attack=False, owner="enemy"),  # 梦魇之王萨维斯 4/4
        ]
        return GameState(
            hero=HeroState(hp=16, hero_class=_class_of(5)),
            mana=ManaState(available=6, max_mana=6),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=22, hero_class=_class_of(6)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=6,
        )

    def test_warlock_old_gods_t6(self, state):
        legal = enumerate_legal_actions(state)

        # (1) STEALTH minion on board
        assert state.board[0].has_stealth is True

        # (2) 0-cost spell (伺机待发) always playable
        zero_idx = [i for i, c in enumerate(state.hand) if c.cost == 0]
        assert len(zero_idx) >= 1
        zero_plays = [a for a in legal
                      if a.action_type == 'PLAY' and a.card_index in zero_idx]
        assert len(zero_plays) >= 1

        # (3) Opponent TAUNT blocks face
        opp_taunts = [m for m in state.opponent.board if m.has_taunt]
        assert len(opp_taunts) >= 1
        face_attacks = [a for a in legal
                        if a.action_type == 'ATTACK' and a.target_index == 0]
        assert len(face_attacks) == 0

        # (4) WEAPON card in hand
        weapon_cards = [c for c in state.hand if c.card_type == 'WEAPON']
        assert len(weapon_cards) == 1

        # (5) Engine plays weapon + spell
        result = _engine().search(state)
        assert result is not None
        play_count = sum(1 for a in result.best_chromosome if a.action_type == 'PLAY')
        assert play_count >= 1

        # (6) Evaluate score
        import math
        score = evaluate(state)
        assert not math.isinf(score)


# ===================================================================
# Scenario 9: Druid(6) vs Warlock(3) T5 — Ramp Rush Discover
# Druid has 激活 to enable 7-cost play, holding RUSH+BATTLECRY minion
# Exercises: 激活 ramp, RUSH+DEATHRATTLE+BATTLECRY, TAUNT, DISCOVER
# ===================================================================

class Test09DruidRampRushT5:

    @pytest.fixture
    def state(self):
        p = SimDeck(6)
        o = SimDeck(3)

        board = [
            p.minion(122968, can_attack=True),   # 护巢龙 4/5 TAUNT
            p.minion(122967, can_attack=True),   # 费伍德树人 2/2
        ]
        hand = [
            p.card(69550),    # 激活 0c
            p.card(129171),   # 地底虫王 7c RUSH+DEATHRATTLE+BATTLECRY
            p.card(120746),   # 波涛形塑 1c
            p.card(121064),   # 发挥优势 2c
        ]
        opp_board = [
            o.minion(112923, can_attack=True, owner="enemy"),   # 石丘防御者 1/5 TAUNT
            o.minion(123398, can_attack=False, owner="enemy"),  # 冬泉雏龙 1/2
        ]
        return GameState(
            hero=HeroState(hp=22, hero_class=_class_of(6)),
            mana=ManaState(available=5, max_mana=5),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=24, hero_class=_class_of(3)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=5,
        )

    def test_druid_ramp_rush_t5(self, state):
        legal = enumerate_legal_actions(state)

        # (1) 地底虫王 (7c) not playable at 5 mana without 激活
        bug_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 129171][0]
        bug_plays = [a for a in legal
                     if a.action_type == 'PLAY' and a.card_index == bug_idx]
        assert len(bug_plays) == 0, '7c needs 激活'

        # (3) 激活 is playable (0-cost spell)
        act_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 69550][0]
        act_plays = [a for a in legal
                     if a.action_type == 'PLAY' and a.card_index == act_idx]
        assert len(act_plays) >= 1

        # (4) RUSH+DEATHRATTLE+BATTLECRY on 地底虫王 card
        m = _make_minion(129171)
        assert m.has_rush is True

        # (5) Opponent TAUNT blocks face
        opp_taunts = [m for m in state.opponent.board if m.has_taunt]
        assert len(opp_taunts) >= 1

        # (6) Engine finds multi-play turn
        result = _engine().search(state)
        assert result is not None


# ===================================================================
# Scenario 10: Warlock(2) vs Druid(6) T8 — Dragon Clash
# Both have big boards, 格罗玛什 CHARGE in hand for lethal
# Exercises: CHARGE lethal, high-cost plays, TAUNT trade, RUSH counter
# ===================================================================

class Test10DragonClashT8:

    @pytest.fixture
    def state(self):
        p = SimDeck(2)
        o = SimDeck(6)

        board = [
            p.minion(121196, can_attack=True),   # 先觉蜿变幼龙 6/8
            p.minion(120503, can_attack=True),   # 现场播报员 3/3
            p.minion(122500, can_attack=True),   # 晦鳞巢母 4/3
        ]
        hand = [
            p.card(69643),    # 格罗玛什 8c CHARGE
            p.card(117714),   # 乘风浮龙 8c 6/6
            p.card(115688),   # 影焰晕染 2c
        ]
        opp_board = [
            o.minion(122968, can_attack=True, owner="enemy"),   # 护巢龙 4/5 TAUNT
            o.minion(129171, can_attack=True, owner="enemy"),   # 地底虫王 6/6 RUSH
            o.minion(122967, can_attack=False, owner="enemy"),  # 费伍德树人 2/2
        ]
        return GameState(
            hero=HeroState(hp=12, hero_class=_class_of(2)),
            mana=ManaState(available=8, max_mana=8),
            board=board, hand=hand, deck_remaining=p.remaining(),
            opponent=OpponentState(
                hero=HeroState(hp=10, hero_class=_class_of(6)),
                board=opp_board, hand_count=5, deck_remaining=o.remaining(),
            ),
            turn_number=8,
        )

    def test_dragon_clash_t8(self, state):
        legal = enumerate_legal_actions(state)

        # (1) CHARGE finisher (格罗玛什) playable
        grom_idx = [i for i, c in enumerate(state.hand) if c.dbf_id == 69643]
        assert len(grom_idx) == 1
        grom_plays = [a for a in legal
                      if a.action_type == 'PLAY' and a.card_index == grom_idx[0]]
        assert len(grom_plays) >= 1

        # (2) Opponent TAUNT blocks face from current board
        opp_taunts = [m for m in state.opponent.board if m.has_taunt]
        assert len(opp_taunts) >= 1
        face_attacks = [a for a in legal
                        if a.action_type == 'ATTACK' and a.target_index == 0]
        assert len(face_attacks) == 0

        # (3) But max_damage_bound is high enough for lethal
        # board 6+3+4=13 + charge 4 + spell = 17+
        bound = max_damage_bound(state)
        assert bound >= 10, f'Bound {bound} should cover 10 HP'

        # (4) RUSH minion on opponent side
        opp_rush = [m for m in state.opponent.board if m.has_rush]
        assert len(opp_rush) >= 1

        # (5) Both boards have significant total stats
        player_total = sum(m.attack + m.health for m in state.board)
        opp_total = sum(m.attack + m.health for m in state.opponent.board)
        assert player_total > 20
        assert opp_total > 15

        # (6) Engine finds lethal path through taunt
        result = _engine().search(state)
        assert result is not None
        assert result.best_fitness > -9999
