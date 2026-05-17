# Fix Audit Issues — Main Agent Work Record

## Task: Fix all issues from end-to-end audit of hs_analysis project

### Files Modified:
1. **analysis/watcher/global_tracker.py** — P0 #1, P0 #2, P1 #4, P1 #9, P2 #11, P2 #13, P2 #14, P2 #17
2. **tracker/log_monitor.py** — P0 #3, P1 #5, P1 #8
3. **analysis/watcher/tracker_rules.py** — P1 #7
4. **analysis/watcher/state_bridge.py** — P1 #10
5. **analysis/search/game_state.py** — P1 #10 (added fields to OpponentState)

### Changes Summary:

#### global_tracker.py:
- Added `birth_turn: int = 0` to `_EntityBirth` dataclass (P0 #2)
- Set `birth_turn=self.state.current_turn` in `on_full_entity` (P0 #2)
- Added `_entity_played_set: Set[int]` to prevent double counting (P0 #1)
- Added double-count check at start of `_on_card_played` (P0 #1)
- Clear `_entity_played_set` in `on_game_start` (P0 #1)
- Changed `_classify_source` to use `birth.birth_turn == 0` instead of `self.state.current_turn == 0` (P0 #2)
- Added zone handlers: HAND→GRAVEYARD, DECK→PLAY, HAND→DECK (P1 #4, P2 #11)
- Added `_on_zone_hand_to_graveyard` method (P1 #4)
- Added `_on_zone_deck_to_play` and `_on_zone_hand_to_deck` methods (P2 #11)
- Fixed `opp_initial_deck_size` filter to only count MINION/SPELL/WEAPON/LOCATION (P2 #13)
- Skip cards_played clearing when is_first_player is default and current_turn==0 (P1 #9)
- Prune opp_known_hand_types with 2-turn cutoff in on_turn_change (P2 #14)
- Replace `list.remove()` with list comprehension for secrets removal (P2 #17)

#### log_monitor.py:
- Use `_last_known_zones.get(entity_id, fields.zone)` as initial_zone for on_full_entity (P0 #3)
- Always call on_full_entity for opponent DECK entities even without card_id (P1 #5)
- Only call on_show_entity for opponent entities NOT in DECK zone (P1 #8)

#### tracker_rules.py:
- Removed `current_turn > 0` guard in RevealTrackerRule.on_show_entity (P1 #7)

#### state_bridge.py:
- Added FieldMapping entries for opp_known_deck_cards, opp_known_hand_types, opp_entity_transforms (P1 #10)
- Added serialization loop for CardRevealRecord lists (P1 #10)

#### game_state.py:
- Added 9 new fields to OpponentState (P1 #10)
- Updated copy() method to include new fields (P1 #10)

### All Tests Passed
