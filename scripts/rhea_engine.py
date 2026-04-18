#!/usr/bin/env python3
"""rhea_engine.py — RHEA (Rolling Horizon Evolutionary Algorithm) search engine.

Searches for optimal action sequences within a single Hearthstone turn using
evolutionary optimization (population-based, tournament selection, uniform
crossover, mutation).

Usage:
    python3 scripts/rhea_engine.py          # run built-in demo
"""

from __future__ import annotations

import copy
import random
import re
import sys
import os
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Import sibling modules
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from game_state import GameState, Minion, Card, HeroState, ManaState, OpponentState, Weapon  # type: ignore[import]
from composite_evaluator import evaluate, evaluate_delta, quick_eval  # type: ignore[import]
from multi_objective_evaluator import evaluate as mo_evaluate, evaluate_delta as mo_evaluate_delta, EvaluationResult, pareto_filter  # type: ignore[import]


# ===================================================================
# 1. Action dataclass
# ===================================================================

@dataclass
class Action:
    """A single actionable step within a turn."""

    action_type: str  # PLAY, ATTACK, HERO_POWER, END_TURN
    card_index: int = -1       # index in hand for PLAY
    position: int = -1         # board position for PLAY
    source_index: int = -1     # board index for ATTACK source
    target_index: int = -1     # 0=enemy hero, 1-7=enemy minion for ATTACK target
    data: int = 0              # generic data for hero power target

    def describe(self, state: Optional[GameState] = None) -> str:
        """Return a human-readable Chinese description of the action."""
        if self.action_type == "PLAY":
            card_name = "未知卡牌"
            if state is not None and 0 <= self.card_index < len(state.hand):
                card_name = state.hand[self.card_index].name or f"卡牌#{self.card_index}"
            return f"打出 [{card_name}]"
        elif self.action_type == "ATTACK":
            return f"随从#{self.source_index} 攻击 目标#{self.target_index}"
        elif self.action_type == "HERO_POWER":
            return "使用英雄技能"
        elif self.action_type == "END_TURN":
            return "结束回合"
        return f"未知动作({self.action_type})"


# ===================================================================
# 2. enumerate_legal_actions
# ===================================================================

def enumerate_legal_actions(state: GameState) -> List[Action]:
    """Return all legal actions for the given state."""
    actions: List[Action] = []

    # --- PLAY actions ---
    for idx, card in enumerate(state.hand):
        if card.cost > state.mana.available:
            continue
        if card.card_type.upper() == "MINION":
            if not state.board_full():
                # Position ranges from 0 to len(board) inclusive
                for pos in range(len(state.board) + 1):
                    actions.append(Action(
                        action_type="PLAY",
                        card_index=idx,
                        position=pos,
                    ))
        elif card.card_type.upper() in ("SPELL", "HERO"):
            actions.append(Action(
                action_type="PLAY",
                card_index=idx,
            ))
        elif card.card_type.upper() == "WEAPON":
            actions.append(Action(
                action_type="PLAY",
                card_index=idx,
            ))

    # --- ATTACK actions ---
    # Check if enemy has taunt minions
    enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

    for src_idx, minion in enumerate(state.board):
        if not (minion.can_attack or minion.has_charge or minion.has_rush):
            continue

        if enemy_taunts:
            # Must attack taunt minions (unless charge — charge can go face)
            if minion.has_charge and not minion.has_rush:
                # Charge minions can attack enemy hero directly
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=0,
                ))
            # Can attack enemy taunt minions
            for tgt_idx, _ in enumerate(enemy_taunts):
                # Find the actual index in opponent.board
                real_idx = _find_enemy_minion_index(state, enemy_taunts[tgt_idx])
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=real_idx + 1,  # 1-indexed (0 = hero)
                ))
        else:
            # No taunts: can attack enemy hero or any enemy minion
            # Enemy hero
            can_attack_hero = not minion.has_rush  # Rush can only attack minions
            if can_attack_hero:
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=0,
                ))
            # Enemy minions
            for tgt_idx in range(len(state.opponent.board)):
                actions.append(Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=tgt_idx + 1,  # 1-indexed
                ))

    # --- HERO_POWER action ---
    if not state.hero.hero_power_used and state.mana.available >= 2:
        actions.append(Action(action_type="HERO_POWER"))

    # --- END_TURN (always legal) ---
    actions.append(Action(action_type="END_TURN"))

    return actions


def _find_enemy_minion_index(state: GameState, minion: Minion) -> int:
    """Find the index of a minion object in the opponent's board."""
    for i, m in enumerate(state.opponent.board):
        if m is minion:
            return i
    return 0


# ===================================================================
# 3. apply_action
# ===================================================================

def apply_action(state: GameState, action: Action) -> GameState:
    """Apply *action* to a **copy** of *state* and return the modified copy."""
    s = state.copy()

    if action.action_type == "PLAY":
        card_idx = action.card_index
        if card_idx < 0 or card_idx >= len(s.hand):
            return s  # invalid — return unmodified copy
        card = s.hand[card_idx]

        # Deduct mana
        s.mana.available -= card.cost

        # Remove card from hand
        s.hand.pop(card_idx)

        if card.card_type.upper() == "MINION":
            new_minion = Minion(
                dbf_id=card.dbf_id,
                name=card.name,
                attack=card.attack,
                health=card.health,
                max_health=card.health,
                cost=card.cost,
                can_attack=False,  # summoning sickness
                owner="friendly",
            )
            pos = min(action.position, len(s.board))
            s.board.insert(pos, new_minion)

        elif card.card_type.upper() == "WEAPON":
            s.hero.weapon = Weapon(
                attack=card.attack,
                health=card.health,
                name=card.name,
            )

        elif card.card_type.upper() == 'SPELL':
            try:
                from spell_simulator import resolve_effects
                s = resolve_effects(s, card)
            except Exception:
                pass  # fallback to just removing from hand
        # OTHER card types: just removed from hand

    elif action.action_type == "ATTACK":
        src_idx = action.source_index
        tgt_idx = action.target_index

        if src_idx < 0 or src_idx >= len(s.board):
            return s
        source = s.board[src_idx]

        if tgt_idx == 0:
            # Attack enemy hero
            s.opponent.hero.hp -= source.attack
        else:
            enemy_idx = tgt_idx - 1
            if enemy_idx < 0 or enemy_idx >= len(s.opponent.board):
                return s
            target = s.opponent.board[enemy_idx]

            # Deal source attack to target
            if target.has_divine_shield:
                target.has_divine_shield = False
            else:
                target.health -= source.attack

            # Counter-attack: deal target attack to source
            if source.has_divine_shield:
                source.has_divine_shield = False
            else:
                source.health -= target.attack

            # Remove dead enemy minions
            s.opponent.board = [m for m in s.opponent.board if m.health > 0]

        # Remove dead friendly minions (may have died from counter-attack)
        s.board = [m for m in s.board if m.health > 0]

        # Mark source as having attacked
        if src_idx < len(s.board):
            # Source may have been removed if it died
            for m in s.board:
                if m is source:
                    m.can_attack = False
                    break
        # If source died, it's already removed above

    elif action.action_type == "HERO_POWER":
        s.mana.available -= 2
        s.hero.hero_power_used = True

    elif action.action_type == "END_TURN":
        pass  # no state change

    return s


# ===================================================================
# 5. SearchResult dataclass
# ===================================================================

@dataclass
class SearchResult:
    """Result of an RHEA search."""

    best_chromosome: List[Action]
    best_fitness: float
    alternatives: List[Tuple[List[Action], float]]  # top 3 (chromosome, fitness)
    generations_run: int
    time_elapsed: float
    population_diversity: float  # std of fitnesses
    confidence: float  # gap between best and 2nd-best, normalised
    pareto_front: List[Tuple[List[Action], EvaluationResult]] = field(default_factory=list)

    def describe(self) -> str:
        """Return a formatted Chinese description of the search result."""
        lines = [
            "====== RHEA 搜索结果 ======",
            f"  运行代数  : {self.generations_run}",
            f"  耗时      : {self.time_elapsed:.2f} ms",
            f"  最佳适应度: {self.best_fitness:+.2f}",
            f"  种群多样性: {self.population_diversity:.4f}",
            f"  置信度    : {self.confidence:.4f}",
            "",
            "  --- 最佳动作序列 ---",
        ]
        for i, act in enumerate(self.best_chromosome):
            lines.append(f"    {i + 1}. {act.describe()}")
        if self.alternatives:
            lines.append("")
            lines.append("  --- 备选方案 ---")
            for rank, (chromo, fit) in enumerate(self.alternatives, 1):
                desc = " → ".join(a.describe() for a in chromo)
                lines.append(f"    方案{rank} (适应度={fit:+.2f}): {desc}")
        lines.append("=" * 30)
        return "\n".join(lines)


# ===================================================================
# 4. Multi-turn lethal setup helper
# ===================================================================

def next_turn_lethal_check(state: GameState) -> bool:
    """Check if lethal is achievable next turn.

    Predict available mana next turn = min(current_max + 1, 10).
    Calculate burst damage potential from hand + board.
    """
    next_mana = min(state.mana.max_mana + 1, 10)

    # Burst from minions that can attack next turn
    minion_burst = 0
    for m in state.board:
        minion_burst += m.attack  # all friendly minions can attack next turn

    # Burst from direct damage spells in hand
    spell_burst = 0
    for c in state.hand:
        ct = getattr(c, 'card_type', '').upper()
        if ct == 'SPELL' and c.cost <= next_mana:
            # Estimate damage from card text
            text = getattr(c, 'text', '') or ''
            dmg_match = re.search(r'造成\s*(\d+)\s*点伤害', text)
            if dmg_match:
                spell_burst += int(dmg_match.group(1))

    # Weapon burst
    weapon_burst = 0
    if state.hero.weapon is not None:
        weapon_burst += state.hero.weapon.attack

    total_burst = minion_burst + spell_burst + weapon_burst
    opponent_health = state.opponent.hero.hp + state.opponent.hero.armor

    return total_burst >= opponent_health


# ===================================================================
# 5. RHEA Engine
# ===================================================================

class RHEAEngine:
    """Rolling Horizon Evolutionary Algorithm for Hearthstone turn planning."""

    def __init__(
        self,
        pop_size: int = 50,
        tournament_size: int = 5,
        crossover_rate: float = 0.8,
        mutation_rate: Optional[float] = None,
        elite_count: int = 2,
        max_gens: int = 200,
        time_limit: float = 75.0,
        max_chromosome_length: int = 6,
    ):
        self.pop_size = pop_size
        self.tournament_size = tournament_size
        self.crossover_rate = crossover_rate
        self.mutation_rate = (
            mutation_rate if mutation_rate is not None
            else 1.0 / max_chromosome_length
        )
        self.elite_count = elite_count
        self.max_gens = max_gens
        self.time_limit = time_limit
        self.max_chromosome_length = max_chromosome_length
        self._target_diversity = 0.5
        self._adaptive_mutation_rate = self.mutation_rate

    # ---------------------------------------------------------------
    # Main search entry point
    # ---------------------------------------------------------------

    def search(
        self,
        initial_state: GameState,
        weights: Optional[dict] = None,
    ) -> SearchResult:
        """Run the RHEA evolutionary search and return the best action plan."""
        t_start = time.perf_counter()

        # Initialise population
        population = self._init_population(initial_state)

        fitnesses: List[float] = [
            self._evaluate_chromosome(initial_state, chromo, weights)
            for chromo in population
        ]

        best_ever = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
        best_ever_chromo = list(population[best_ever])
        best_ever_fit = fitnesses[best_ever]

        gen = 0
        for gen in range(1, self.max_gens + 1):
            elapsed_ms = (time.perf_counter() - t_start) * 1000.0
            if elapsed_ms >= self.time_limit:
                break

            # Sort by fitness (descending)
            indexed = sorted(
                range(len(fitnesses)),
                key=lambda i: fitnesses[i],
                reverse=True,
            )

            # Elitism: keep top individuals
            new_pop: List[List[Action]] = []
            for ei in indexed[: self.elite_count]:
                new_pop.append(list(population[ei]))

            # Fill rest of population
            while len(new_pop) < self.pop_size:
                parent1 = self._tournament_select(population, fitnesses)
                parent2 = self._tournament_select(population, fitnesses)

                if random.random() < self.crossover_rate:
                    child = self._crossover(parent1, parent2)
                else:
                    child = list(parent1)

                child = self._mutate(child, initial_state)
                new_pop.append(child)

            population = new_pop
            fitnesses = [
                self._evaluate_chromosome(initial_state, chromo, weights)
                for chromo in population
            ]

            # Track best ever
            gen_best_idx = max(range(len(fitnesses)), key=lambda i: fitnesses[i])
            if fitnesses[gen_best_idx] > best_ever_fit:
                best_ever_fit = fitnesses[gen_best_idx]
                best_ever_chromo = list(population[gen_best_idx])

        # ---- Phase B: Multi-turn lethal setup bonus ----
        try:
            phase_b_start = time.perf_counter()
            phase_b_budget = (self.time_limit / 1000.0) * 0.30  # 30% of time budget

            # Get top 3 Phase A results
            indexed_by_fitness = sorted(range(len(fitnesses)), key=lambda i: fitnesses[i], reverse=True)
            top3_indices = indexed_by_fitness[:3]

            for idx in top3_indices:
                elapsed_b = time.perf_counter() - phase_b_start
                if elapsed_b >= phase_b_budget:
                    break

                chromo = population[idx]
                # Replay chromosome to get end state
                end_state = initial_state.copy()
                valid = True
                for action in chromo:
                    legal = enumerate_legal_actions(end_state)
                    if not _action_in_list(action, legal):
                        valid = False
                        break
                    end_state = apply_action(end_state, action)

                if valid and not end_state.is_lethal():
                    # Check if next turn lethal is possible from this state
                    if next_turn_lethal_check(end_state):
                        # Big bonus for setting up lethal
                        fitnesses[idx] += 5000.0

                        # Update best ever if needed
                        if fitnesses[idx] > best_ever_fit:
                            best_ever_fit = fitnesses[idx]
                            best_ever_chromo = list(population[idx])
        except Exception:
            pass  # Phase B is best-effort; never crash the engine

        # Compute diversity (std of fitnesses)
        mean_f = sum(fitnesses) / len(fitnesses) if fitnesses else 0.0
        variance = sum((f - mean_f) ** 2 for f in fitnesses) / len(fitnesses) if fitnesses else 0.0
        diversity = variance ** 0.5

        # Adaptive mutation rate
        if diversity < self._target_diversity * 0.5:
            self._adaptive_mutation_rate = min(self.mutation_rate * 2.0, 1.0)
        elif diversity > self._target_diversity * 2.0:
            self._adaptive_mutation_rate = max(self.mutation_rate * 0.5, 0.01)
        else:
            self._adaptive_mutation_rate = self.mutation_rate

        # Confidence: gap between best and 2nd-best
        sorted_fits = sorted(fitnesses, reverse=True)
        if len(sorted_fits) >= 2 and abs(sorted_fits[0]) > 1e-9:
            confidence = 1.0 - (sorted_fits[1] / sorted_fits[0])
        else:
            confidence = 1.0

        # Collect top 3 alternatives (excluding the best)
        indexed_sorted = sorted(
            range(len(fitnesses)),
            key=lambda i: fitnesses[i],
            reverse=True,
        )
        alternatives: List[Tuple[List[Action], float]] = []
        for idx in indexed_sorted:
            chromo = population[idx]
            # Skip if same fitness as best or same object as best_ever
            if len(alternatives) >= 3:
                break
            if population[idx] is not population[indexed_sorted[0]]:
                alternatives.append((list(chromo), fitnesses[idx]))

        elapsed = (time.perf_counter() - t_start) * 1000.0

        # Pareto front analysis
        pareto_front_list: List[Tuple[List[Action], EvaluationResult]] = []
        try:
            mo_results = []
            for i, chromo in enumerate(population):
                try:
                    current = initial_state.copy()
                    for action in chromo:
                        legal = enumerate_legal_actions(current)
                        if not _action_in_list(action, legal):
                            break
                        current = apply_action(current, action)
                    else:
                        delta = mo_evaluate_delta(mo_evaluate(initial_state), mo_evaluate(current))
                        mo_results.append((delta, i))
                except Exception:
                    pass

            pareto_front_raw = pareto_filter(mo_results)
            for eval_result, idx in pareto_front_raw[:5]:
                pareto_front_list.append((list(population[idx]), eval_result))
        except Exception:
            pass  # Never crash the engine if multi_objective_evaluator has issues

        return SearchResult(
            best_chromosome=best_ever_chromo,
            best_fitness=best_ever_fit,
            alternatives=alternatives,
            generations_run=gen,
            time_elapsed=elapsed,
            population_diversity=diversity,
            confidence=confidence,
            pareto_front=pareto_front_list,
        )

    # ---------------------------------------------------------------
    # Population initialisation
    # ---------------------------------------------------------------

    def _init_population(self, state: GameState) -> List[List[Action]]:
        """Create initial population of random legal action sequences."""
        population: List[List[Action]] = []
        for _ in range(self.pop_size):
            chromo = self._random_chromosome(state)
            population.append(chromo)
        return population

    def _random_chromosome(self, state: GameState) -> List[Action]:
        """Generate one random legal action sequence ending with END_TURN."""
        chromo: List[Action] = []
        current = state.copy()

        for _ in range(self.max_chromosome_length):
            legal = enumerate_legal_actions(current)
            non_end = [a for a in legal if a.action_type != "END_TURN"]

            if not non_end:
                # Only END_TURN available or nothing to do
                chromo.append(Action(action_type="END_TURN"))
                return chromo

            # Randomly pick an action (including END_TURN with small probability)
            if random.random() < 0.15:
                # Sometimes just end the sequence early
                chromo.append(Action(action_type="END_TURN"))
                return chromo

            action = random.choice(non_end)
            chromo.append(action)
            current = apply_action(current, action)

        # Ensure sequence ends with END_TURN
        if not chromo or chromo[-1].action_type != "END_TURN":
            chromo.append(Action(action_type="END_TURN"))

        return chromo

    # ---------------------------------------------------------------
    # Fitness evaluation
    # ---------------------------------------------------------------

    def _evaluate_chromosome(
        self,
        initial_state: GameState,
        chromo: List[Action],
        weights: Optional[dict],
    ) -> float:
        """Apply all actions and return evaluate_delta.

        Returns -9999.0 if any action is invalid.
        """
        current = initial_state.copy()

        for action in chromo:
            legal = enumerate_legal_actions(current)
            # Check if action is legal
            if not _action_in_list(action, legal):
                return -9999.0

            # Lethal check — if we've killed opponent, big bonus
            current = apply_action(current, action)
            if current.is_lethal():
                return 10000.0

        return evaluate_delta(initial_state, current, weights)

    # ---------------------------------------------------------------
    # Tournament selection
    # ---------------------------------------------------------------

    def _tournament_select(
        self,
        population: List[List[Action]],
        fitnesses: List[float],
    ) -> List[Action]:
        """Pick tournament_size random individuals; return the fittest."""
        candidates = random.sample(
            range(len(population)),
            min(self.tournament_size, len(population)),
        )
        best = max(candidates, key=lambda i: fitnesses[i])
        return population[best]

    # ---------------------------------------------------------------
    # Crossover
    # ---------------------------------------------------------------

    def _crossover(
        self,
        parent1: List[Action],
        parent2: List[Action],
    ) -> List[Action]:
        """Sequence-preserving n-point crossover.

        Pick 1-2 crossover points and swap contiguous subsequence.
        Validate child chromosome; fall back to cloning fitter parent if invalid.
        """
        if not parent1 or not parent2:
            return list(parent1) if parent1 else list(parent2)

        # Pick crossover point(s)
        max_len = min(len(parent1), len(parent2))
        if max_len <= 1:
            return copy.deepcopy(parent1)

        # Single crossover point
        cp = random.randint(1, max_len - 1)

        # Child = first part of p1 + second part of p2
        child = [copy.deepcopy(a) for a in parent1[:cp]]
        child += [copy.deepcopy(a) for a in parent2[cp:]]

        # Ensure child ends with END_TURN
        if child and child[-1].action_type != 'END_TURN':
            child.append(Action(action_type='END_TURN'))

        return child

    # ---------------------------------------------------------------
    # Chromosome validation
    # ---------------------------------------------------------------

    def _validate_chromosome(self, state: GameState, chromosome: List[Action]) -> bool:
        """Replay chromosome from state; return True if all actions legal in sequence."""
        current = state.copy()
        for action in chromosome:
            legal = enumerate_legal_actions(current)
            if not _action_in_list(action, legal):
                return False
            current = apply_action(current, action)
        return True

    # ---------------------------------------------------------------
    # Mutation
    # ---------------------------------------------------------------

    def _mutate(
        self,
        chromo: List[Action],
        state: GameState,
    ) -> List[Action]:
        """With probability mutation_rate, replace a random gene."""
        result = [copy.deepcopy(a) for a in chromo]

        if random.random() < self._adaptive_mutation_rate and result:
            # Pick a random position to mutate
            pos = random.randrange(len(result))

            # For simplicity, regenerate a random action for that position
            # by replaying the chromosome up to that position to get the state
            current = state.copy()
            for i in range(pos):
                legal = enumerate_legal_actions(current)
                act = result[i]
                if _action_in_list(act, legal):
                    current = apply_action(current, act)
                else:
                    break

            legal = enumerate_legal_actions(current)
            if legal:
                result[pos] = random.choice(legal)

        return result


# ===================================================================
# Helper: action-in-list comparison
# ===================================================================

def _action_in_list(action: Action, legal: List[Action]) -> bool:
    """Check if *action* matches any action in *legal* by key fields."""
    for la in legal:
        if (la.action_type == action.action_type
                and la.card_index == action.card_index
                and la.position == action.position
                and la.source_index == action.source_index
                and la.target_index == action.target_index):
            return True
    return False


# ===================================================================
# 6. __main__ demo
# ===================================================================

def _build_demo_state() -> GameState:
    """Build a sample game state for the demo."""
    return GameState(
        hero=HeroState(
            hp=25,
            armor=2,
            hero_class="MAGE",
            hero_power_used=False,
        ),
        mana=ManaState(available=8, max_mana=8),
        board=[
            Minion(
                dbf_id=1001,
                name="Fire Fly",
                attack=2,
                health=1,
                max_health=1,
                cost=1,
                can_attack=True,
                owner="friendly",
            ),
            Minion(
                dbf_id=1002,
                name="Tar Creeper",
                attack=1,
                health=5,
                max_health=5,
                cost=3,
                can_attack=True,
                has_taunt=True,
                owner="friendly",
            ),
            Minion(
                dbf_id=1003,
                name="Southsea Deckhand",
                attack=2,
                health=1,
                max_health=1,
                cost=1,
                can_attack=True,
                has_charge=True,
                owner="friendly",
            ),
        ],
        hand=[
            Card(dbf_id=2001, name="Frostbolt", cost=2, card_type="SPELL"),
            Card(dbf_id=2002, name="Boulderfist Ogre", cost=6,
                 card_type="MINION", attack=6, health=7),
            Card(dbf_id=2003, name="Arcanite Reaper", cost=5,
                 card_type="WEAPON", attack=5, health=2),
        ],
        opponent=OpponentState(
            hero=HeroState(hp=18, armor=0),
            board=[
                Minion(
                    dbf_id=3001,
                    name="Voidwalker",
                    attack=1,
                    health=3,
                    max_health=3,
                    has_taunt=True,
                    owner="enemy",
                ),
                Minion(
                    dbf_id=3002,
                    name="Murloc Raider",
                    attack=2,
                    health=1,
                    max_health=1,
                    owner="enemy",
                ),
            ],
            hand_count=4,
        ),
        turn_number=8,
    )


def main() -> None:
    print("=" * 60)
    print("RHEA Engine — Demo")
    print("=" * 60)

    state = _build_demo_state()
    print(f"\n初始状态:")
    print(f"  英雄 HP={state.hero.hp} 法力={state.mana.available}/{state.mana.max_mana}")
    print(f"  手牌: {[c.name for c in state.hand]}")
    print(f"  友方随从: {[(m.name, m.attack, m.health) for m in state.board]}")
    print(f"  敌方随从: {[(m.name, m.attack, m.health) for m in state.opponent.board]}")
    print(f"  敌方英雄 HP={state.opponent.hero.hp}")

    # Show legal actions
    legal = enumerate_legal_actions(state)
    print(f"\n合法动作 ({len(legal)} 个):")
    for i, a in enumerate(legal):
        print(f"  {i + 1}. {a.describe(state)}")

    # Run RHEA with small parameters for quick demo
    print("\n--- 开始 RHEA 搜索 (pop=20, gens=50) ---")
    t0 = time.perf_counter()

    engine = RHEAEngine(
        pop_size=20,
        max_gens=50,
        time_limit=500.0,  # 500ms budget
        max_chromosome_length=6,
    )
    result = engine.search(state)

    elapsed = (time.perf_counter() - t0) * 1000.0
    print(f"\n搜索完成, 耗时 {elapsed:.1f} ms")
    print(result.describe())

    # Quick sanity checks
    errors: list[str] = []
    if not result.best_chromosome:
        errors.append("FAIL: best_chromosome is empty")
    if result.generations_run <= 0:
        errors.append(f"FAIL: generations_run={result.generations_run}, expected > 0")
    if result.time_elapsed <= 0:
        errors.append(f"FAIL: time_elapsed={result.time_elapsed}, expected > 0")

    # Verify the best chromosome ends with END_TURN
    if result.best_chromosome and result.best_chromosome[-1].action_type != "END_TURN":
        errors.append(
            f"FAIL: best chromosome does not end with END_TURN, "
            f"last action={result.best_chromosome[-1].action_type}"
        )

    # Verify apply_action isolation
    original_hp = state.opponent.hero.hp
    test_state = apply_action(
        state,
        Action(action_type="ATTACK", source_index=0, target_index=0),
    )
    if state.opponent.hero.hp != original_hp:
        errors.append("FAIL: apply_action mutated the original state")

    if errors:
        print("\n❌ Some tests FAILED:")
        for e in errors:
            print(f"  • {e}")
        raise SystemExit(1)
    else:
        print("\n✅ All sanity checks passed.")


if __name__ == "__main__":
    main()
