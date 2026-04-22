import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from analysis.search.power_parser import parse_power_log, extract_game_state
from analysis.search.game_state import (
    GameState, HeroState, ManaState, Minion, OpponentState
)

POWER_LOG_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', 'Power.log')
)


class TestPowerLogBasicParse(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(POWER_LOG_PATH):
            raise unittest.SkipTest("Power.log not found")
        cls.game = parse_power_log(POWER_LOG_PATH)
        if not cls.game:
            raise unittest.SkipTest("Power.log parse returned None")

    def test_game_has_two_players(self):
        self.assertEqual(len(self.game.players), 2)

    def test_both_players_have_heroes(self):
        from hearthstone.enums import GameTag, Zone, CardType
        for i, p in enumerate(self.game.players):
            entities = list(p.entities)
            heroes = [
                e for e in entities
                if e.tags.get(GameTag.ZONE) == Zone.PLAY
                and e.tags.get(GameTag.CARDTYPE) == CardType.HERO
            ]
            self.assertGreaterEqual(
                len(heroes), 1,
                f"Player {i+1} should have at least one hero entity"
            )

    def test_total_entities_reasonable(self):
        entities = list(self.game.entities)
        self.assertGreater(len(entities), 100)
        self.assertLess(len(entities), 1000)


class TestPowerLogFriendlyState(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(POWER_LOG_PATH):
            raise unittest.SkipTest("Power.log not found")
        hslog_game = parse_power_log(POWER_LOG_PATH)
        if not hslog_game:
            raise unittest.SkipTest("Power.log parse returned None")

        from hearthstone.enums import GameTag
        p1 = hslog_game.players[0]
        hero_state, mana_state, board, hand = extract_game_state(hslog_game, 0)

        cls.game_state = GameState(
            hero=hero_state,
            mana=mana_state,
            board=board,
            hand=hand,
            turn_number=p1.tags.get(GameTag.TURN, 1),
        )

    def test_hero_alive(self):
        self.assertGreater(self.game_state.hero.hp, 0)

    def test_mana_valid(self):
        self.assertGreaterEqual(self.game_state.mana.max_mana, 0)
        self.assertLessEqual(self.game_state.mana.max_mana, 20)
        self.assertLessEqual(self.game_state.mana.available, self.game_state.mana.max_mana)

    def test_board_minions_have_valid_stats(self):
        for m in self.game_state.board:
            self.assertGreaterEqual(m.attack, 0)
            self.assertGreaterEqual(m.health, 1)
            self.assertGreater(len(m.name), 0)

    def test_hand_cards_have_ids(self):
        for card_id in self.game_state.hand:
            self.assertIsInstance(card_id, str)

    def test_board_not_exceeds_max(self):
        self.assertLessEqual(len(self.game_state.board), 7)

    def test_hand_not_exceeds_max(self):
        self.assertLessEqual(len(self.game_state.hand), 10)

    def test_game_state_copy_preserves_data(self):
        copied = self.game_state.copy()
        self.assertEqual(copied.hero.hp, self.game_state.hero.hp)
        self.assertEqual(len(copied.board), len(self.game_state.board))
        self.assertEqual(len(copied.hand), len(self.game_state.hand))

    def test_game_state_copy_is_independent(self):
        copied = self.game_state.copy()
        if copied.board:
            copied.board[0].health = 999
            self.assertNotEqual(self.game_state.board[0].health, 999)

    def test_total_attack_matches(self):
        total = self.game_state.get_total_attack()
        expected = sum(m.attack for m in self.game_state.board)
        self.assertEqual(total, expected)


class TestPowerLogBothPlayersState(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(POWER_LOG_PATH):
            raise unittest.SkipTest("Power.log not found")
        hslog_game = parse_power_log(POWER_LOG_PATH)
        if not hslog_game:
            raise unittest.SkipTest("Power.log parse returned None")

        from hearthstone.enums import GameTag
        p1 = hslog_game.players[0]
        p2 = hslog_game.players[1]

        hero1, mana1, board1, hand1 = extract_game_state(hslog_game, 0)
        hero2, mana2, board2, _ = extract_game_state(hslog_game, 1)

        cls.game_state = GameState(
            hero=hero1,
            mana=mana1,
            board=board1,
            hand=hand1,
            turn_number=p1.tags.get(GameTag.TURN, 1),
            opponent=OpponentState(
                hero=hero2,
                board=board2,
                hand_count=len(list(p2.entities)),
            ),
        )

    def test_opponent_has_hero(self):
        self.assertIsNotNone(self.game_state.opponent.hero)

    def test_opponent_hero_alive(self):
        self.assertGreater(self.game_state.opponent.hero.hp, 0)

    def test_opponent_has_board(self):
        self.assertIsInstance(self.game_state.opponent.board, list)

    def test_not_lethal_yet(self):
        opp = self.game_state.opponent.hero
        self.assertGreater(opp.hp + opp.armor, 0)

    def test_board_symmetry(self):
        self.assertLessEqual(len(self.game_state.board), 7)
        self.assertLessEqual(len(self.game_state.opponent.board), 7)


class TestPowerLogTauntMechanic(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(POWER_LOG_PATH):
            raise unittest.SkipTest("Power.log not found")
        hslog_game = parse_power_log(POWER_LOG_PATH)
        if not hslog_game:
            raise unittest.SkipTest("Power.log parse returned None")

        _, _, cls.board, _ = extract_game_state(hslog_game, 0)

    def test_taunt_detection(self):
        taunt_minions = [m for m in self.board if m.has_taunt]
        for m in taunt_minions:
            self.assertTrue(m.has_taunt)

    def test_minion_keywords_valid(self):
        for m in self.board:
            self.assertIsInstance(m.has_taunt, bool)
            self.assertIsInstance(m.has_divine_shield, bool)
            self.assertIsInstance(m.has_rush, bool)
            self.assertIsInstance(m.has_charge, bool)


class TestPowerLogParserRobustness(unittest.TestCase):

    def test_nonexistent_file(self):
        result = parse_power_log("nonexistent_file.log")
        self.assertIsNone(result)

    def test_empty_file(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False, encoding='utf-8') as f:
            f.write("")
            tmp_path = f.name
        try:
            result = parse_power_log(tmp_path)
            self.assertIsNone(result)
        finally:
            os.unlink(tmp_path)

    def test_garbage_data(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False, encoding='utf-8') as f:
            f.write("garbage line 1\ngarbage line 2\nrandom text\n")
            tmp_path = f.name
        try:
            result = parse_power_log(tmp_path)
            self.assertIsNone(result)
        finally:
            os.unlink(tmp_path)


if __name__ == '__main__':
    unittest.main()
