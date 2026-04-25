#!/usr/bin/env python3
"""test_live_games.py — Integration tests with real game logs.

Validates the full pipeline: Power.log → GameTracker → StateBridge → Engine search → DecisionPresenter.
Uses 3 diverse real games extracted from Hearthstone_2026_04_23_08_43_35.
"""

import pytest
from pathlib import Path
from io import StringIO

from hearthstone.enums import GameTag, Zone as HZone

from analysis.watcher.game_tracker import GameTracker
from analysis.watcher.state_bridge import StateBridge
from analysis.search.engine_adapter import UnifiedSearchResult, ActionProb, create_engine
from analysis.search.rhea.actions import Action, ActionType
from analysis.watcher.decision_loop import DecisionPresenter
from analysis.utils.score_provider import load_scores_into_hand


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

FIXTURE_GAMES = {
    "warrior_vs_warrior": {
        "file": "game1_warrior_vs_warrior_8t.log",
        "max_turn": 4,
        "our_turns": 2,
        "friendly_idx": 1,  # Player 2 (后手)
    },
    "dk_vs_rogue": {
        "file": "game3_dk_vs_rogue_21t.log",
        "max_turn": 11,
        "our_turns": 5,
        "friendly_idx": 1,  # Player 2
    },
    "rogue_vs_priest": {
        "file": "game7_rogue_vs_priest_26t.log",
        "max_turn": 13,
        "our_turns": 7,
        "friendly_idx": 0,  # Player 1 (先手)
    },
}


# ── Helpers ──────────────────────────────────────────────────────────


def _detect_friendly_idx(game) -> int:
    """Detect which player is the friendly (logging) player by checking visible hand cards."""
    if not game or len(game.players) < 2:
        return 0
    vis = []
    for p in game.players:
        count = sum(
            1 for e in getattr(p, "entities", [])
            if getattr(e, "card_id", "") and getattr(e, "tags", {}).get(GameTag.ZONE) == HZone.HAND
        )
        vis.append(count)
    # The friendly player sees their own cards, so more visible cards = friendly
    return 1 if vis[1] > vis[0] else 0


def _parse_game(game_name: str):
    """Parse a fixture game fully and return (tracker, game, friendly_idx)."""
    info = FIXTURE_GAMES[game_name]
    path = str(FIXTURES_DIR / info["file"])

    tracker = GameTracker()
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            tracker.feed_line(line.rstrip("\n"))

    game = tracker.export_entities()
    friendly_idx = _detect_friendly_idx(game)
    return tracker, game, friendly_idx


def _extract_turn_states(game_name: str, min_turn: int = 1):
    """Feed lines incrementally, exporting state at each of our turns >= min_turn.

    Returns list of (turn_number, state) for each of our turn-start events.
    """
    info = FIXTURE_GAMES[game_name]
    path = str(FIXTURES_DIR / info["file"])
    friendly_idx = info["friendly_idx"]

    tracker = GameTracker()
    bridge = StateBridge(entity_cache=tracker.entity_cache)
    results = []

    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            event = tracker.feed_line(line.rstrip("\n"))
            if event == "turn_start":
                current_turn = tracker.get_current_turn()
                # Determine if it's our turn:
                # Player 1 (idx=0) turns: odd (1,3,5...)
                # Player 2 (idx=1) turns: even (2,4,6...)
                is_our_turn = (current_turn % 2 != friendly_idx)
                if is_our_turn and current_turn >= min_turn:
                    game = tracker.export_entities()
                    if game is not None:
                        state = bridge.convert(game, player_index=friendly_idx)
                        if state and state.turn_number > 0:
                            results.append((current_turn, state))

    return results


# ── Session-scoped fixtures ──────────────────────────────────────────


@pytest.fixture(scope="session")
def parsed_games():
    """Parse all 3 fixture games once per session. Returns dict of game_name → (tracker, game, friendly_idx)."""
    return {name: _parse_game(name) for name in FIXTURE_GAMES}


@pytest.fixture(scope="session")
def game_states_for_search():
    """Extract mid-game states (turn >= 3) from each game for engine search tests."""
    states = {}
    for name in FIXTURE_GAMES:
        turn_states = _extract_turn_states(name, min_turn=3)
        if turn_states:
            # Use the first qualifying turn for search tests
            _, state = turn_states[0]
            load_scores_into_hand(state)
            states[name] = state
    return states


# ════════════════════════════════════════════════════════════════════
# 1. TestGameParsing — Verify parsing works for all 3 games
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("game_name", list(FIXTURE_GAMES.keys()))
class TestGameParsing:
    """Verify GameTracker parses all fixture logs without errors."""

    def test_tracker_loads_successfully(self, parsed_games, game_name):
        """GameTracker should parse all lines and be in a valid state."""
        tracker, game, friendly_idx = parsed_games[game_name]
        assert tracker.game_count >= 1, f"{game_name}: should have parsed at least 1 game"

    def test_has_two_players(self, parsed_games, game_name):
        """Each game should have exactly 2 players."""
        tracker, game, friendly_idx = parsed_games[game_name]
        assert game is not None, f"{game_name}: game export should not be None"
        players = list(game.players)
        assert len(players) == 2, f"{game_name}: expected 2 players, got {len(players)}"

    def test_both_heroes_alive(self, parsed_games, game_name):
        """Both heroes should have HP > 0 at final state."""
        from hearthstone.enums import CardType
        tracker, game, friendly_idx = parsed_games[game_name]
        for player in game.players:
            hero_found = False
            for entity in player.entities:
                if (entity.tags.get(GameTag.ZONE) == HZone.PLAY
                        and entity.tags.get(GameTag.CARDTYPE) == CardType.HERO):
                    hp = entity.tags.get(GameTag.HEALTH, 0)
                    damage = entity.tags.get(GameTag.DAMAGE, 0)
                    effective_hp = hp - damage
                    assert effective_hp > 0, (
                        f"{game_name}: hero should have HP > 0, got {effective_hp} "
                        f"(base={hp}, damage={damage})"
                    )
                    hero_found = True
                    break
            assert hero_found, f"{game_name}: player should have a hero entity in PLAY zone"

    def test_friendly_player_detected(self, parsed_games, game_name):
        """Friendly player should be detected based on visible hand cards."""
        tracker, game, friendly_idx = parsed_games[game_name]
        expected = FIXTURE_GAMES[game_name]["friendly_idx"]
        assert friendly_idx == expected, (
            f"{game_name}: friendly_idx={friendly_idx}, expected={expected}"
        )


# ════════════════════════════════════════════════════════════════════
# 2. TestStateConversion — Verify StateBridge produces valid GameState
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize("game_name", list(FIXTURE_GAMES.keys()))
class TestStateConversion:
    """Verify StateBridge.convert() produces valid GameState for each fixture."""

    def test_state_not_none(self, parsed_games, game_name):
        """StateBridge should produce a non-None GameState."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        assert state is not None, f"{game_name}: state should not be None"

    def test_turn_number_positive(self, parsed_games, game_name):
        """Turn number should be > 0."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        assert state.turn_number > 0, f"{game_name}: turn_number={state.turn_number}"

    def test_hero_alive(self, parsed_games, game_name):
        """Our hero should have HP > 0."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        assert state.hero.hp > 0, f"{game_name}: hero HP={state.hero.hp}"

    def test_mana_valid(self, parsed_games, game_name):
        """Mana should be 0 <= available <= max_mana <= 10."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        assert 0 <= state.mana.available, f"{game_name}: mana.available={state.mana.available}"
        assert state.mana.available <= state.mana.max_mana, (
            f"{game_name}: available({state.mana.available}) > max_mana({state.mana.max_mana})"
        )
        assert 0 <= state.mana.max_mana <= 10, f"{game_name}: max_mana={state.mana.max_mana}"

    def test_hand_valid(self, parsed_games, game_name):
        """Hand size should be 0-10, each card should have a name."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        assert 0 <= len(state.hand) <= 10, f"{game_name}: hand size={len(state.hand)}"
        for i, card in enumerate(state.hand):
            assert hasattr(card, "name"), f"{game_name}: card {i} missing 'name' attr"
            assert hasattr(card, "cost"), f"{game_name}: card {i} missing 'cost' attr"

    def test_board_valid(self, parsed_games, game_name):
        """Board size should be 0-7, minions should have valid stats."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        assert 0 <= len(state.board) <= 7, f"{game_name}: board size={len(state.board)}"
        for i, minion in enumerate(state.board):
            assert minion.attack >= 0, f"{game_name}: minion {i} attack={minion.attack}"
            assert minion.health > 0, f"{game_name}: minion {i} health={minion.health}"

    def test_opponent_valid(self, parsed_games, game_name):
        """Opponent should have valid hero and board."""
        tracker, game, friendly_idx = parsed_games[game_name]
        bridge = StateBridge(entity_cache=tracker.entity_cache)
        state = bridge.convert(game, player_index=friendly_idx)
        opp = state.opponent
        assert opp is not None, f"{game_name}: opponent should not be None"
        assert opp.hero.hp > 0, f"{game_name}: opponent hero HP={opp.hero.hp}"
        assert 0 <= len(opp.board) <= 7, f"{game_name}: opponent board size={len(opp.board)}"
        assert opp.hand_count >= 0, f"{game_name}: opponent hand_count={opp.hand_count}"


# ════════════════════════════════════════════════════════════════════
# 3. TestEngineSearch — Verify search produces valid results
# ════════════════════════════════════════════════════════════════════


class TestEngineSearch:
    """Run actual search on extracted game states with minimal budget."""

    @pytest.fixture(scope="class")
    def game_states(self, game_states_for_search):
        """Return dict of {game_name: GameState} for engine search."""
        return game_states_for_search

    @pytest.mark.parametrize("engine_name", ["rhea", "mcts"])
    def test_search_returns_result(self, game_states, engine_name):
        """Each engine should produce a valid SearchResult."""
        if not game_states:
            pytest.skip("No game states available for search")

        # Use the first available state
        state = next(iter(game_states.values()))

        params = {
            "rhea": {"pop_size": 4, "max_gens": 2, "time_limit": 50, "max_chromosome_length": 3},
            "mcts": {"time_budget_ms": 200, "num_worlds": 2},
        }[engine_name]

        engine_factory = create_engine(engine_name, params)
        engine = engine_factory()
        raw_result = engine.search(state)
        result = UnifiedSearchResult(raw_result)

        assert result is not None
        assert result.best_chromosome is not None

    @pytest.mark.parametrize("engine_name", ["rhea", "mcts"])
    def test_best_sequence_not_empty(self, game_states, engine_name):
        """Best action sequence should be non-empty."""
        if not game_states:
            pytest.skip("No game states available for search")

        state = next(iter(game_states.values()))

        params = {
            "rhea": {"pop_size": 4, "max_gens": 2, "time_limit": 50, "max_chromosome_length": 3},
            "mcts": {"time_budget_ms": 200, "num_worlds": 2},
        }[engine_name]

        engine_factory = create_engine(engine_name, params)
        engine = engine_factory()
        raw_result = engine.search(state)
        result = UnifiedSearchResult(raw_result)

        assert len(result.best_chromosome) > 0, (
            f"{engine_name}: best_chromosome should not be empty"
        )

    @pytest.mark.parametrize("engine_name", ["rhea", "mcts"])
    def test_sequence_ends_with_end_turn(self, game_states, engine_name):
        """Sequence should end with END_TURN."""
        if not game_states:
            pytest.skip("No game states available for search")

        state = next(iter(game_states.values()))

        params = {
            "rhea": {"pop_size": 4, "max_gens": 2, "time_limit": 50, "max_chromosome_length": 3},
            "mcts": {"time_budget_ms": 200, "num_worlds": 2},
        }[engine_name]

        engine_factory = create_engine(engine_name, params)
        engine = engine_factory()
        raw_result = engine.search(state)
        result = UnifiedSearchResult(raw_result)

        assert result.best_chromosome[-1].action_type == ActionType.END_TURN, (
            f"{engine_name}: last action should be END_TURN, "
            f"got {result.best_chromosome[-1].action_type}"
        )

    @pytest.mark.parametrize("engine_name", ["rhea", "mcts"])
    def test_search_on_all_games(self, game_states, engine_name):
        """Each engine should produce results for all available game states."""
        if not game_states:
            pytest.skip("No game states available for search")

        params = {
            "rhea": {"pop_size": 4, "max_gens": 2, "time_limit": 50, "max_chromosome_length": 3},
            "mcts": {"time_budget_ms": 200, "num_worlds": 2},
        }[engine_name]

        for game_name, state in game_states.items():
            engine_factory = create_engine(engine_name, params)
            engine = engine_factory()
            raw_result = engine.search(state)
            result = UnifiedSearchResult(raw_result)

            assert len(result.best_chromosome) > 0, (
                f"{engine_name} on {game_name}: best_chromosome should not be empty"
            )
            assert result.best_chromosome[-1].action_type == ActionType.END_TURN, (
                f"{engine_name} on {game_name}: last action should be END_TURN"
            )

    @pytest.mark.parametrize("engine_name", ["rhea", "mcts"])
    def test_best_fitness_is_finite(self, game_states, engine_name):
        """Best fitness should be a finite number."""
        if not game_states:
            pytest.skip("No game states available for search")

        state = next(iter(game_states.values()))

        params = {
            "rhea": {"pop_size": 4, "max_gens": 2, "time_limit": 50, "max_chromosome_length": 3},
            "mcts": {"time_budget_ms": 200, "num_worlds": 2},
        }[engine_name]

        engine_factory = create_engine(engine_name, params)
        engine = engine_factory()
        raw_result = engine.search(state)
        result = UnifiedSearchResult(raw_result)

        import math
        assert math.isfinite(result.best_fitness), (
            f"{engine_name}: best_fitness should be finite, got {result.best_fitness}"
        )


# ════════════════════════════════════════════════════════════════════
# 4. TestDecisionPresenter — Verify presenter output format
# ════════════════════════════════════════════════════════════════════


class TestDecisionPresenter:
    """Test DecisionPresenter produces correct output format."""

    @staticmethod
    def _make_mock_result(has_mcts_stats=False, has_action_probs=False):
        """Create a mock UnifiedSearchResult for presenter tests."""

        class MockResult:
            pass

        raw = MockResult()
        # MCTS-style fields (now the only path)
        raw.best_sequence = [
            Action(action_type=ActionType.PLAY, card_index=0),
            Action(action_type=ActionType.END_TURN),
        ]
        raw.fitness = 1.5
        raw.best_chromosome = raw.best_sequence  # backward compat
        raw.best_fitness = raw.fitness
        raw.alternatives = []
        raw.action_stats = []
        raw.confidence = 0.8
        raw.population_diversity = 0.3
        raw.generations_run = 5
        raw.timings = {"utp": 1.2, "rhea": 3.4}

        if has_mcts_stats:
            from types import SimpleNamespace
            raw.mcts_stats = SimpleNamespace(
                iterations=100,
                nodes_created=50,
                evaluations=100,
                world_count=3,
                time_used_ms=200.0,
            )
            raw.detailed_log = None
            raw.action_stats = []
        else:
            raw.mcts_stats = None

        return UnifiedSearchResult(raw)

    @staticmethod
    def _make_mock_state():
        """Create a minimal mock GameState for presenter tests."""
        from analysis.search.game_state import (
            GameState, HeroState, ManaState, Minion, OpponentState,
        )
        from analysis.models.card import Card

        state = GameState()
        state.hero = HeroState(hp=30, max_hp=30, armor=0, hero_class="WARRIOR")
        state.mana = ManaState(available=5, max_mana=5)
        state.hand = [
            Card(card_id="EX1_001", name="夜色镇炼金师", cost=1),
            Card(card_id="EX1_002", name="怒火中烧", cost=2),
        ]
        state.board = [
            Minion(attack=3, health=2, max_health=2, cost=2, can_attack=True,
                   has_taunt=False, has_divine_shield=False, card_id="CS2_120",
                   name="鱼人猎潮者"),
        ]
        state.turn_number = 5
        state.deck_remaining = 20
        state.opponent = OpponentState(
            hero=HeroState(hp=28, max_hp=30, armor=0, hero_class="MAGE"),
            board=[],
            hand_count=5,
        )
        return state

    def test_output_contains_board_state(self):
        """With show_board=True, output should contain [场面] line."""
        output = StringIO()
        presenter = DecisionPresenter(output=output, show_board=True)
        result = self._make_mock_result()
        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "[场面]" in text, f"Output should contain [场面], got:\n{text}"

    def test_output_contains_best_action(self):
        """Output should contain ★ 最优抉择."""
        output = StringIO()
        presenter = DecisionPresenter(output=output, show_board=True)
        result = self._make_mock_result()
        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "★ 最优抉择" in text, f"Output should contain ★ 最优抉择, got:\n{text}"

    def test_output_contains_probabilities_for_mcts(self):
        """With MCTS action_probs, output should contain [概率分布]."""
        output = StringIO()
        presenter = DecisionPresenter(
            output=output, show_board=True, show_probabilities=True,
        )

        # Create result with action_probs
        result = self._make_mock_result(has_mcts_stats=True)
        # Manually set action_probs
        result.action_probs = [
            ActionProb(
                action=Action(action_type=ActionType.PLAY, card_index=0),
                visit_count=50,
                probability=0.6,
                win_rate=0.55,
                q_value=0.1,
            ),
            ActionProb(
                action=Action(action_type=ActionType.END_TURN),
                visit_count=30,
                probability=0.4,
                win_rate=0.45,
                q_value=-0.1,
            ),
        ]

        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "[概率分布]" in text, f"Output should contain [概率分布], got:\n{text}"

    def test_output_contains_mcts_stats(self):
        """With mcts_stats, output should contain [MCTS] section."""
        output = StringIO()
        presenter = DecisionPresenter(
            output=output, show_board=True, show_mcts_detail=True,
        )

        # Create a mock MCTS result (has best_sequence, not best_chromosome)
        from types import SimpleNamespace

        class MockMCTSResult:
            pass

        raw = MockMCTSResult()
        raw.best_sequence = [
            Action(action_type=ActionType.PLAY, card_index=0),
            Action(action_type=ActionType.END_TURN),
        ]
        raw.fitness = 1.2
        raw.alternatives = []
        raw.mcts_stats = SimpleNamespace(
            iterations=100,
            nodes_created=50,
            evaluations=100,
            world_count=3,
            time_used_ms=200.0,
        )
        raw.detailed_log = None
        raw.action_stats = []

        result = UnifiedSearchResult(raw)
        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "[MCTS]" in text, f"Output should contain [MCTS], got:\n{text}"

    def test_output_suppressed_when_disabled(self):
        """With show_board=False, no [场面] should appear."""
        output = StringIO()
        presenter = DecisionPresenter(output=output, show_board=False)
        result = self._make_mock_result()
        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "[场面]" not in text, f"Output should NOT contain [场面] when disabled, got:\n{text}"

    def test_output_no_rhea_stats(self):
        """RHEA output section is disabled — should NOT contain [RHEA]."""
        output = StringIO()
        presenter = DecisionPresenter(output=output, show_board=True)
        result = self._make_mock_result(has_mcts_stats=False)
        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "[RHEA]" not in text, f"[RHEA] section should be disabled, got:\n{text}"

    def test_output_turn_number(self):
        """Output header should contain the turn number."""
        output = StringIO()
        presenter = DecisionPresenter(output=output, show_board=True)
        result = self._make_mock_result()
        state = self._make_mock_state()
        presenter.present(result, state, 100.0)
        text = output.getvalue()
        assert "Turn 5" in text, f"Output should contain 'Turn 5', got:\n{text}"


# ════════════════════════════════════════════════════════════════════
# 5. TestLiveGameIntegration — Full pipeline per-game
# ════════════════════════════════════════════════════════════════════


class TestLiveGameIntegration:
    """End-to-end test: full game log → decisions for each turn."""

    def test_warrior_game_produces_decisions(self):
        """Game 1: Warrior vs Warrior should produce decision states for our turns."""
        turn_states = _extract_turn_states("warrior_vs_warrior", min_turn=1)
        # Warrior game has 2 of our turns total
        assert len(turn_states) >= 1, (
            f"Warrior game should produce at least 1 decision state, got {len(turn_states)}"
        )
        # Verify each state is valid
        for turn_num, state in turn_states:
            assert state.turn_number > 0
            assert state.hero.hp > 0
            assert len(state.hand) >= 0

    def test_dk_game_state_progression(self):
        """Game 3: State should progress through turns correctly."""
        turn_states = _extract_turn_states("dk_vs_rogue", min_turn=1)
        assert len(turn_states) >= 2, (
            f"DK game should produce at least 2 decision states, got {len(turn_states)}"
        )
        # Verify turn numbers increase monotonically
        prev_turn = 0
        for turn_num, state in turn_states:
            assert turn_num > prev_turn, (
                f"Turn numbers should increase: {turn_num} <= {prev_turn}"
            )
            assert state.turn_number > 0
            prev_turn = turn_num

    def test_rogue_game_handles_long_game(self):
        """Game 7: Should handle 7+ turns without errors."""
        turn_states = _extract_turn_states("rogue_vs_priest", min_turn=1)
        assert len(turn_states) >= 3, (
            f"Rogue game should produce at least 3 decision states, got {len(turn_states)}"
        )
        # Each state should be valid
        for turn_num, state in turn_states:
            assert state.turn_number > 0
            assert state.hero.hp > 0
            assert 0 <= len(state.board) <= 7
            assert 0 <= len(state.hand) <= 10

    def test_full_pipeline_with_search(self):
        """Full pipeline: parse → state → search → present for one game."""
        # Pick dk_vs_rogue as medium-length game
        turn_states = _extract_turn_states("dk_vs_rogue", min_turn=3)
        if not turn_states:
            pytest.skip("No qualifying turn states from dk_vs_rogue game")

        _, state = turn_states[0]
        load_scores_into_hand(state)

        # Run RHEA search
        engine_factory = create_engine("rhea", {
            "pop_size": 4, "max_gens": 2, "time_limit": 50, "max_chromosome_length": 3,
        })
        engine = engine_factory()
        raw_result = engine.search(state)
        result = UnifiedSearchResult(raw_result)

        # Present
        output = StringIO()
        presenter = DecisionPresenter(output=output, show_board=True)
        presenter.present(result, state, 50.0)

        text = output.getvalue()
        assert "★ 最优抉择" in text
        assert "END_TURN" in text or "结束回合" in text
        assert "[场面]" in text

    def test_full_pipeline_mcts(self):
        """Full pipeline with MCTS engine for one game."""
        turn_states = _extract_turn_states("rogue_vs_priest", min_turn=3)
        if not turn_states:
            pytest.skip("No qualifying turn states from rogue_vs_priest game")

        _, state = turn_states[0]
        load_scores_into_hand(state)

        # Run MCTS search
        engine_factory = create_engine("mcts", {
            "time_budget_ms": 200, "num_worlds": 2,
        })
        engine = engine_factory()
        raw_result = engine.search(state)
        result = UnifiedSearchResult(raw_result)

        # Present
        output = StringIO()
        presenter = DecisionPresenter(
            output=output, show_board=True, show_probabilities=True, show_mcts_detail=True,
        )
        presenter.present(result, state, 200.0)

        text = output.getvalue()
        assert "★ 最优抉择" in text
        assert "[MCTS]" in text
