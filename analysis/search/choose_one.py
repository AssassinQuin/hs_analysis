"""choose_one.py — Choose One (抉择) mechanic for Hearthstone AI.

Druid-exclusive mechanic: when playing a Choose One card, pick one of two
mutually exclusive effects. If Fandral Staghelm is on board, both effects apply.
"""

from __future__ import annotations

import re
from analysis.search.game_state import GameState, Minion
from analysis.models.card import Card
from analysis.evaluators.composite import target_selection_eval


def is_choose_one(card) -> bool:
    mechanics = set(getattr(card, 'mechanics', []) or [])
    text = getattr(card, 'text', '') or ''
    return 'CHOOSE_ONE' in mechanics or '抉择' in text


def has_fandral(state: GameState) -> bool:
    for m in state.board:
        name = (getattr(m, 'name', '') or '').lower()
        if 'fandral' in name or '范达尔' in name or '鹿盔' in name:
            return True
    return False


def parse_choose_options(card_text: str) -> list[dict]:
    if not card_text:
        return []
    parts = re.split(r'[；;]\s*或者\s*|[；;]\s*—or\s*', card_text)
    if len(parts) < 2:
        parts = re.split(r'抉择[：:]\s*', card_text)
        if len(parts) >= 2:
            parts = parts[1:]
            sub = re.split(r'[；;]\s*或者?\s*', parts[0]) if parts else []
            if len(sub) >= 2:
                parts = sub
    options = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        effects = _parse_option_effects(p)
        options.append({'text': p, 'effects': effects})
    return options[:2]


def _parse_option_effects(text: str) -> list[tuple]:
    effects = []
    m = re.search(r'(\d+)/(\d+)', text)
    if m:
        effects.append(('transform_stats', int(m.group(1)), int(m.group(2))))
    m = re.search(r"Gain\s*(\d+)\s*(?:Armor|armor)", text)
    if not m:
        m = re.search(r'获得\s*\+?\s*(\d+)\s*点?护甲', text)
    if m:
        effects.append(('armor', int(m.group(1))))
    m = re.search(r"Gain\s*\+?\s*(\d+)\s*(?:Attack|attack)", text)
    if not m:
        m = re.search(r'获得\s*\+?\s*(\d+)\s*点?攻击力', text)
    if m:
        effects.append(('buff_attack', int(m.group(1))))
    m = re.search(r"Summon\s*(?:a\s+)?(\d+)/(\d+)", text)
    if not m:
        m = re.search(r'召唤\s*(?:一个\s*)?(\d+)/(\d+)', text)
    if m:
        effects.append(('summon', int(m.group(1)), int(m.group(2))))
    m = re.search(r"Draw\s*(\d+)", text)
    if not m:
        m = re.search(r'抽\s*(\d+)\s*张', text)
    if m:
        effects.append(('draw', int(m.group(1))))
    if '嘲讽' in text:
        effects.append(('give_taunt',))
    if '冲锋' in text:
        effects.append(('give_charge',))
    if '突袭' in text:
        effects.append(('give_rush',))
    if not effects:
        effects.append(('no_effect',))
    return effects


def resolve_choose_one(state: GameState, card: Card, minion: Minion) -> GameState:
    if not has_fandral(state):
        options = parse_choose_options(getattr(card, 'text', '') or '')
        if not options:
            return state
        best = _pick_best_option(state, options, minion)
        return _apply_option(state, best, minion)
    else:
        options = parse_choose_options(getattr(card, 'text', '') or '')
        for opt in options:
            state = _apply_option(state, opt, minion)
        return state


def _pick_best_option(state: GameState, options: list[dict], minion: Minion) -> dict:
    if len(options) == 1:
        return options[0]
    best_score = float('-inf')
    best_opt = options[0]
    for opt in options:
        try:
            sim = state.copy()
            sim = _apply_option(sim, opt, minion)
            score = target_selection_eval(sim)
            if score > best_score:
                best_score = score
                best_opt = opt
        except Exception:
            continue
    return best_opt


def _apply_option(state: GameState, option: dict, minion: Minion) -> GameState:
    s = state
    for eff in option.get('effects', []):
        if eff[0] == 'transform_stats':
            s.board = [m for m in s.board if m is not minion]
            minion.attack = eff[1]
            minion.health = eff[2]
            minion.max_health = eff[2]
            s.board.append(minion)
        elif eff[0] == 'armor':
            s.hero.armor += eff[1]
        elif eff[0] == 'buff_attack':
            minion.attack += eff[1]
        elif eff[0] == 'summon':
            from analysis.utils.spell_simulator import EffectApplier
            s = EffectApplier.apply_summon(s, eff[1], eff[2])
        elif eff[0] == 'draw':
            from analysis.utils.spell_simulator import EffectApplier
            s = EffectApplier.apply_draw(s, eff[1])
        elif eff[0] == 'give_taunt':
            minion.has_taunt = True
        elif eff[0] == 'give_charge':
            minion.has_charge = True
            minion.can_attack = True
        elif eff[0] == 'give_rush':
            minion.has_rush = True
    return s
