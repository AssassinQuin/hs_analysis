---
session: ses_25a4
updated: 2026-04-19T12:42:42.348Z
---

# Session Summary

## Goal
Compile comprehensive, detailed rules for 12 Hearthstone mechanics from 2025-2026 expansions (Year of the Scarab) by searching official sources, wikis, and community guides.

## Constraints & Preferences
- Thoroughness level: very thorough
- Sources preferred: Blizzard official pages, Hearthstone Top Decks, Chinese community guides (gamersky, 17173, zhihu), patch notes, wiki.gg, outof.games
- Must cover all 12 requested mechanics: Imbue, Herald, Shatter, Kindred, Rewind, Fabled, Colossal, Dark Gift, Hand Targeting, Discover, Dormant, Choose One
- Chinese terminology provided for several mechanics (灌注, 兆示, 裂变, 延系, 回溯, 传说, 巨型, 黑暗之赐, 休眠)

## Progress
### Done
- [x] **Imbue** — Full rules found (wiki.gg). Mechanic from Into the Emerald Dream. Replaces hero power with class-specific Imbue hero power. Each subsequent Imbue increments all bold numbers by 1 (except cost). DK, Druid, Hunter, Mage, Paladin, Priest, Rogue, Shaman get Imbue powers; DH, Warlock, Warrior get no effect. If Imbue hero power was replaced then Imbued again, continues from previous numbers. Copying enemy Imbue hero power copies base form only. DK/Rogue Imbue powers added in Echoes mini-set (Patch 34.4).
- [x] **Discover** — Full rules found (wiki.gg). Choose 1 of 3 cards to add to hand. Pool is neutral + class cards by default. No duplicate options. Must choose one (random if timer expires). Cannot Discover copies of self. Card placed in hand at end of current Sequence. "Discover any card" = any class or neutral. "Discover from another class" = only class cards, excludes neutral. Class bonus (4x weight) removed for random pools since Patch 15.2.
- [x] **Kindred** — Full rules found (wiki.gg). Mechanic from Lost City of Un'Goro. Bonus if you played same minion type/spell school last turn. Only activates from hand. Separate from Battlecry unless Kindred modifies Battlecry with "instead" (then Brann works). Dual-type minions only need one type to match.
- [x] **Dark Gift** — Full rules found (wiki.gg). Mechanic from Into the Emerald Dream. 10 total effects: Waking Terror (+3 ATK, Lifesteal), Bundled Up (+4 HP, Taunt), Well Rested (+2/+2, Elusive), Sleepwalker (Charge, only 1+ ATK), Harpy's Talons (Divine Shield, Windfury), Persisting Horror (Reborn with full HP), Short Claws (-2 cost, -2 ATK), Rude Awakening (Battlecry x2, only with Battlecry), Living Nightmare (summon 2/2 copy), Sweet Dreams (+4/+5, put on top of deck). Three different Dark Gifts always shown. Applied during Discover. Many classes have Dark Gift granting cards.
- [x] **Rewind** — Full rules found (wiki.gg). Mechanic from Across the Timeways. After playing card with random effect, prompt offers keep or rewind. Rewind reverts entire game state to before card was played, then instantly replays it. Cannot play other cards between. Possible to get same outcome. If multiple Rewind instances, sequential. Morchie from Echoes mini-set keeps BOTH outcomes. If player dies from Rewind card, no rewind option. Turn timer continues during Rewind animation.
- [x] **Shatter** — Full rules found (wiki.gg). Mechanic from Cataclysm. Only on spells. When Shatter spell enters hand, splits into two halves at opposite ends of hand. Each half has full mana cost but half effect. One goes left-most position. When adjacent in hand, recombine into combined card. Full hand = no split. One slot = only left half. Recombined cards merge enchantments. Recombining removes Shatter keyword (won't split again).
- [x] **Herald** — Full rules found (outof.games). Deathwing-aligned classes only (DK, DH, Rogue, Shaman, Warlock, Warrior). Playing Herald minion summons Soldier with same ability as class Colossal appendages. Each Herald upgrades Soldier AND Colossal appendages. 2 Heralds = double power, 4 = double again. Also empowers Deathwing Worldbreaker hero card (2 Herald = 2 Cataclysms, 4 = all 4).
- [x] **Colossal** — Partial rules found (outof.games Cataclysm guide + general knowledge). All classes get Legendary Colossal in Cataclysm. Free random one via Rewards Track. Introduced originally in Voyage to Sunken City. Still need: appendage positioning rules, board space requirements detailed.

### In Progress
- [ ] Fetching Fabled, Colossal (detailed wiki), Dormant, Choose One, Hand Targeting wiki pages from hearthstone.wiki.gg

### Blocked
- Many source websites return 403/404/connection errors: hearthstone.fandom.com, hearthstonetopdecks.com, liquipedia.net, hearthpwn.com, gamersky.com, hs.blizzard.cn.com, Reddit, PCGamer/IGN/Eurogamer/GameSpot. Only reliable sources found: **outof.games** and **hearthstone.wiki.gg**.

## Key Decisions
- **Primary sources**: hearthstone.wiki.gg and outof.games identified as only reliably accessible sources with detailed mechanic content. All other sites (fandom, topdecks, liquipedia, Blizzard official, Chinese community sites) failed due to blocking/errors.
- **Search strategy**: Direct wiki page fetching for specific mechanic keywords proved most effective; general web search returned less useful results.

## Next Steps
1. Fetch remaining wiki pages: `https://hearthstone.wiki.gg/wiki/Fabled`, `https://hearthstone.wiki.gg/wiki/Colossal`, `https://hearthstone.wiki.gg/wiki/Dormant`, `https://hearthstone.wiki.gg/wiki/Choose_One`, `https://hearthstone.wiki.gg/wiki/Hand_targeting` (or similar path)
2. Compile all 12 mechanics into a single comprehensive reference document with the user's requested structure
3. For any mechanics where wiki pages don't exist (Hand Targeting), try outof.games Cataclysm guide pages or general articles
4. Cross-reference Chinese terminology for accuracy where possible

## Critical Context
- **Expansion timeline (Year of the Scarab 2025-2026)**:
  - Into the Emerald Dream → Imbue, Dark Gift
  - The Lost City of Un'Goro → Kindred
  - Across the Timeways → Rewind, Fabled
  - Cataclysm (March 17, 2026, 145 cards) → Herald, Shatter, returning Colossal
  - Echoes of the Infinite mini-set (Jan 13, 2026) → Morchie (Rewind enhancement), DK/Rogue Imbue
- **Cataclysm specifics**: No mini-set; instead 'Class Sets' releasing additional cards. Trial Cards system makes Emerald Dream & Un'Goro sets FREE during Cataclysm.
- **Only two working sources**: hearthstone.wiki.gg and outof.games — all other attempted sites (15+) are blocked or broken.
- **Hand Targeting** is described as a "new mechanic from CATACLYSM" — may need to search for specific card examples or Cataclysm patch notes rather than a dedicated wiki page.

## File Operations
### Read
- (none)

### Modified
- (none)
