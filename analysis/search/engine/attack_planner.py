"""AttackPlanner — deterministic greedy attack sequence optimization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from analysis.search.game_state import GameState, Minion
from analysis.search.rhea_engine import Action, apply_action


@dataclass
class AttackPlan:
    attacks: List[Action]
    score: float
    state_after: Optional[GameState] = None


class AttackPlanner:

    def __init__(self, evaluator=None) -> None:
        self._evaluator = evaluator

    def plan(self, state: GameState) -> AttackPlan:
        attacks: List[Action] = []
        current = state.copy()

        for _ in range(20):
            attacker, target = self._pick_best_attack(current)
            if attacker is None or target is None:
                break

            action = Action(
                action_type="ATTACK",
                source_index=attacker,
                target_index=target,
            )
            attacks.append(action)
            current = apply_action(current, action)

            if current.is_lethal():
                break

        score = self._evaluate_state(state, current)
        return AttackPlan(attacks=attacks, score=score, state_after=current)

    def plan_all_targets(self, state: GameState) -> List[AttackPlan]:
        plans: List[AttackPlan] = []
        first_attacker_idx, _ = self._pick_best_attack(state)
        if first_attacker_idx is None:
            return [AttackPlan(attacks=[], score=self._evaluate_state(state, state))]

        attacker = state.board[first_attacker_idx]
        targets = self._valid_targets(state, attacker)

        for tgt in targets:
            action = Action(
                action_type="ATTACK",
                source_index=first_attacker_idx,
                target_index=tgt,
            )
            next_state = apply_action(state.copy(), action)
            if next_state.is_lethal():
                plan = AttackPlan(
                    attacks=[action],
                    score=1000.0,
                    state_after=next_state,
                )
                return [plan]

            remaining = self.plan(next_state)
            full_attacks = [action] + remaining.attacks
            plan = AttackPlan(
                attacks=full_attacks,
                score=remaining.score,
                state_after=remaining.state_after,
            )
            plans.append(plan)

        if not plans:
            return [AttackPlan(attacks=[], score=self._evaluate_state(state, state))]

        plans.sort(key=lambda p: -p.score)
        return plans

    def _pick_best_attack(self, state: GameState) -> Tuple[Optional[int], Optional[int]]:
        best_src = None
        best_tgt = None
        best_score = -float("inf")
        base_score = self._evaluate_state(state, state)

        for src_idx, minion in enumerate(state.board):
            if not self._can_attack(minion):
                continue
            if minion.frozen_until_next_turn:
                continue
            if minion.is_dormant:
                continue
            if minion.cant_attack:
                continue

            for tgt in self._valid_targets(state, minion):
                action = Action(
                    action_type="ATTACK",
                    source_index=src_idx,
                    target_index=tgt,
                )
                sim = apply_action(state.copy(), action)
                score = self._evaluate_state(state, sim) - base_score

                if sim.is_lethal():
                    return src_idx, tgt

                if score > best_score:
                    best_score = score
                    best_src = src_idx
                    best_tgt = tgt

        if best_src is not None:
            return best_src, best_tgt

        if state.hero.weapon is not None and state.hero.weapon.attack > 0:
            weapon_targets = self._valid_targets(state, None, weapon=True)
            for tgt in weapon_targets:
                action = Action(
                    action_type="ATTACK",
                    source_index=-1,
                    target_index=tgt,
                )
                sim = apply_action(state.copy(), action)
                score = self._evaluate_state(state, sim) - base_score
                if sim.is_lethal():
                    return -1, tgt
                if score > best_score:
                    best_score = score
                    best_src = -1
                    best_tgt = tgt

        return best_src, best_tgt

    def _can_attack(self, minion: Minion) -> bool:
        if minion.can_attack:
            return True
        if minion.has_windfury and minion.has_attacked_once:
            return True
        if minion.has_charge:
            return True
        if minion.has_rush:
            return True
        return False

    def _valid_targets(self, state: GameState, minion: Optional[Minion],
                       weapon: bool = False) -> List[int]:
        targets: List[int] = []
        enemy_taunts = [m for m in state.opponent.board if m.has_taunt]

        if weapon or (minion and not minion.has_rush):
            targets.append(0)

        if enemy_taunts:
            taunt_targets = []
            for i, m in enumerate(state.opponent.board):
                if m.has_taunt:
                    taunt_targets.append(i + 1)
            targets = taunt_targets
            if weapon or (minion and not minion.has_rush):
                pass
        else:
            for i in range(len(state.opponent.board)):
                targets.append(i + 1)

        return targets

    def _evaluate_state(self, before: GameState, after: GameState) -> float:
        if after.is_lethal():
            return 10000.0

        if self._evaluator is not None:
            return self._evaluator.quick_eval(after)

        friend = sum(m.attack + m.health for m in after.board)
        enemy = sum(m.attack + m.health for m in after.opponent.board)
        opp_hp = after.opponent.hero.hp + after.opponent.hero.armor
        hero_hp = after.hero.hp + after.hero.armor
        return (friend - enemy) * 2.0 + opp_hp * -1.0 + hero_hp * 0.5
