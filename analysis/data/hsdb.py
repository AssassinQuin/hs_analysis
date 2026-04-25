# -*- coding: utf-8 -*-
"""Backward-compatible shim — all exports now come from card_data.

This file is kept for import compatibility. New code should import from
``analysis.data.card_data`` directly.
"""
from analysis.data.card_data import (  # noqa: F401
    CardDB,
    get_db,
    get_card,
    get_by_dbf,
    get_hero_class_map,
    reset_db,
    UpdateStatus,
    STANDARD_SETS,
)
