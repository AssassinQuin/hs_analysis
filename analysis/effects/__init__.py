"""effects — Unified card effect parsing & simulation system.

Parser Pattern architecture:
  Types Layer    → types.py         (core data types)
  Parser Layer   → parser/          (card_id + text → structured effects)
  Model Layer    → model/           (effect-centric card/state models)
  Rules Layer    → rules/           (legal action validation)
  Simulation     → simulation/      (effect → state changes)
  Primitives     → primitives/      (low-level execution atoms)
  Executor       → executor.py      (orchestration)
"""
