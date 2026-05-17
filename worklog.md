---
Task ID: 1
Agent: Main Agent
Task: Fix 3 bugs in hs_analysis Hearthstone tracker plugin

Work Log:
- Analyzed uploaded screenshot showing opponent 5 hand cards display issue
- Cloned GitHub repo and performed comprehensive codebase exploration
- Identified 3 root causes for the reported issues:
  1. COIN_CARD_IDS missing current coin card IDs (BAR_COIN1, MUDAN_COIN1)
  2. FIRST_PLAYER tag not bridged in CoreLogMonitor
  3. TAG_CHANGE zone transitions not bridged in CoreLogMonitor
  4. Coin detection only used card_id matching, not COIN_CARD GameTag
  5. deck_codes.txt was stale (missing 2026 Beetle Year decks)

Fixes Applied:
1. Updated COIN_CARD_IDS in hs_enums.py to include BAR_COIN1 and MUDAN_COIN1
2. Added is_coin parameter to on_full_entity() and on_show_entity() in global_tracker.py
3. Added COIN_CARD GameTag detection in _bridge_new_entities() and _bridge_entities_to_global_tracker()
4. Added coin in HAND zone → auto-detect opponent is going second (后手)
5. Enhanced coin_used detection to also check coin_entity_id (not just card_id matching)
6. Added _parse_tag_change_zone() method to CoreLogMonitor for real-time zone change bridging
7. Added _parse_tag_change_first_player() method to CoreLogMonitor for FIRST_PLAYER detection
8. Added entity zone tracking (_entity_zones dict) for zone change detection
9. Fixed log.debug → logger.debug bug in _mark_shuffled_card_played()
10. Updated deck_codes.txt with 10 new 2026 Beetle Year meta decks
11. Reset new tracking state in _on_game_start()

Stage Summary:
- All 11 existing unit tests pass
- Coin detection now works with BAR_COIN1 and MUDAN_COIN1
- FIRST_PLAYER tag is now bridged from Power.log to GlobalTracker
- TAG_CHANGE ZONE events are now bridged (enables coin use detection, card return to hand, etc.)
- deck_codes.txt updated with 10 new 2026 meta decks + existing decks preserved
- Files modified: hs_enums.py, global_tracker.py, log_monitor.py, deck_codes.txt
