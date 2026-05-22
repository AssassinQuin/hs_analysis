#!/usr/bin/env python3
"""Extract detailed card effect chains from Power.log - what actually happened."""
import re
import sys
import json

log_file = sys.argv[1] if len(sys.argv) > 1 else 'Power.log'

with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Build entity -> cardId mapping from SHOW_ENTITY (revealed cards)
card_map = {}
card_names = {}
for line in lines:
    m = re.match(r'.*FULL_ENTITY - Creating ID=(\d+) CardID=(\S+)', line)
    if m:
        eid, card_id = m.group(1), m.group(2)
        if card_id:
            card_map[int(eid)] = card_id
            # Extract name
            nm = re.search(r'entityName=(\S+)', line)
            if nm:
                card_names[int(eid)] = nm.group(1)

    m = re.match(r'.*SHOW_ENTITY - Updating EntityID=(\d+) CardID=(\S+)', line)
    if m:
        eid, card_id = m.group(1), m.group(2)
        if card_id:
            card_map[int(eid)] = card_id
            nm = re.search(r'entityName=(\S+)', line)
            if nm:
                card_names[int(eid)] = nm.group(1)

def resolve_entity(entity_str):
    """Extract cardId and entity info from entity string."""
    eid_m = re.search(r'id=(\d+)', entity_str)
    eid = int(eid_m.group(1)) if eid_m else None
    card_id = card_map.get(eid, '') if eid else ''
    name_m = re.search(r'entityName=(\S+)', entity_str)
    name = name_m.group(1) if name_m else ''
    player_m = re.search(r'player=(\d+)', entity_str)
    player = int(player_m.group(1)) if player_m else None
    zone_m = re.search(r'zone=(\w+)', entity_str)
    zone = zone_m.group(1) if zone_m else ''
    return {'id': eid, 'card_id': card_id, 'name': name, 'player': player, 'zone': zone}

# Parse the log into a structured block tree with tag changes
def parse_blocks(lines):
    blocks = []
    stack = []

    i = 0
    while i < len(lines):
        line = lines[i]
        is_power = 'GameState.DebugPrintPower()' in line or 'PowerTaskList.DebugPrintPower()' in line

        if is_power and 'BLOCK_START' in line:
            bt = re.search(r'BlockType=(\w+)', line)
            ent_raw = re.search(r'Entity=(.+?)(?:\s+EffectCardId|\s*$)', line)
            eff = re.search(r'EffectCardId=(\S+)', line)
            target = re.search(r'Target=(.+?)$', line)

            block_type = bt.group(1) if bt else '?'
            entity = ent_raw.group(1).strip() if ent_raw else ''
            entity = entity.replace('EffectCardId', '').strip()
            effect_card = eff.group(1) if eff else ''
            tgt = target.group(1).strip() if target else ''

            block = {
                'type': block_type,
                'entity': entity,
                'effect_card': effect_card,
                'target': tgt,
                'line': i + 1,
                'children': [],
                'tags': [],  # TAG_CHANGEs inside this block
                'full_entity_create': [],  # FULL_ENTITY / SHOW_ENTITY inside
                'meta': {},
            }
            if stack:
                stack[-1]['children'].append(block)
            else:
                blocks.append(block)
            stack.append(block)

        elif is_power and 'BLOCK_END' in line:
            if stack:
                stack.pop()

        # Capture TAG_CHANGEs
        elif is_power and 'TAG_CHANGE' in line:
            tag_m = re.match(r'.*TAG_CHANGE Entity=(.+?) tag=(\w+) value=(.+)$', line)
            if tag_m and stack:
                entity_str = tag_m.group(1).strip()
                tag_name = tag_m.group(2)
                tag_value = tag_m.group(3).strip()
                stack[-1]['tags'].append({
                    'entity': entity_str,
                    'tag': tag_name,
                    'value': tag_value,
                    'line': i + 1,
                })

        # Capture FULL_ENTITY / SHOW_ENTITY creations
        elif is_power and ('FULL_ENTITY - Creating' in line or 'SHOW_ENTITY - Updating' in line):
            if stack:
                create_m = re.search(r'(?:Creating|Updating)\s+ID=(\d+)\s+CardID=(\S+)', line)
                if create_m:
                    stack[-1]['full_entity_create'].append({
                        'id': int(create_m.group(1)),
                        'card_id': create_m.group(2),
                        'line': i + 1,
                    })

        i += 1

    return blocks

blocks = parse_blocks(lines)

# Extract PLAY blocks with detailed effect info
play_blocks = [b for b in blocks if b['type'] == 'PLAY']

def collect_all_tags(block):
    """Recursively collect all tag changes in a block tree."""
    tags = list(block['tags'])
    for child in block['children']:
        tags.extend(collect_all_tags(child))
    return tags

def collect_all_creates(block):
    creates = list(block['full_entity_create'])
    for child in block['children']:
        creates.extend(collect_all_creates(child))
    return creates

def summarize_effects(block, depth=0):
    """Summarize effects of a PLAY block."""
    all_tags = collect_all_tags(block)
    all_creates = collect_all_creates(block)

    # Categorize effects
    effects = {
        'damage': [],      # HEALTH/ATK reductions
        'buff': [],        # ATK/HEALTH increases
        'zone_change': [], # ZONE changes
        'stat_set': [],    # SET_ATK, SET_HEALTH
        'other_tag': [],   # Other tag changes
        'summons': [],     # New entities created
        'child_plays': [], # Nested PLAY blocks
        'triggers': [],    # TRIGGER blocks
    }

    for t in all_tags:
        tag = t['tag']
        val = t['value']
        ent = resolve_entity(t['entity'])

        if tag == 'ZONE':
            effects['zone_change'].append({**ent, 'to': val, 'line': t['line']})
        elif tag in ('HEALTH', 'DAMAGE'):
            effects['damage'].append({**ent, 'tag': tag, 'value': val, 'line': t['line']})
        elif tag in ('ATK'):
            effects['buff'].append({**ent, 'tag': tag, 'value': val, 'line': t['line']})
        elif tag in ('SET_ATK', 'SET_HEALTH'):
            effects['stat_set'].append({**ent, 'tag': tag, 'value': val, 'line': t['line']})
        else:
            effects['other_tag'].append({**ent, 'tag': tag, 'value': val, 'line': t['line']})

    # New entity creations = summons
    for c in all_creates:
        if c['card_id']:
            effects['summons'].append(c)

    # Count nested play and trigger blocks
    def count_types(block, type_name):
        count = 1 if block['type'] == type_name else 0
        for child in block['children']:
            count += count_types(child, type_name)
        return count

    effects['child_plays_count'] = count_types(block, 'PLAY') - 1  # exclude self
    effects['triggers_count'] = count_types(block, 'TRIGGER')
    effects['deaths_count'] = count_types(block, 'DEATHS')

    return effects

print(f"=== CARD PLAY ANALYSIS ===")
print(f"Total PLAY blocks: {len(play_blocks)}")
print()

# Group unique cards played
unique_cards = {}
for b in play_blocks:
    ent = resolve_entity(b['entity'])
    key = ent['card_id'] or ent['name'] or f"unknown_{ent['id']}"
    if key not in unique_cards:
        unique_cards[key] = {
            'card_id': ent['card_id'],
            'name': ent['name'],
            'player': ent['player'],
            'plays': [],
        }
    unique_cards[key]['plays'].append(b)

print(f"=== UNIQUE CARDS PLAYED: {len(unique_cards)} ===\n")

for card_key, info in sorted(unique_cards.items(), key=lambda x: x[1]['player'] or 0):
    card_id = info['card_id']
    name = info['name']
    player = info['player']
    play_count = len(info['plays'])

    # Only show cards with cardId (opponent cards we know)
    if not card_id:
        continue

    print(f"--- {name} ({card_id}) P{player} x{play_count} ---")

    # Analyze first play in detail
    b = info['plays'][-1]  # last play (most likely resolved)
    eff = summarize_effects(b)

    # Zone changes
    zone_changes = [z for z in eff['zone_change'] if z['to'] in ('PLAY', 'GRAVEYARD', 'HAND', 'DECK', 'SETASIDE', 'SECRET')]
    if zone_changes:
        print(f"  Zone changes: {len(zone_changes)}")
        for z in zone_changes[:10]:
            cid = z.get('card_id', '')
            print(f"    {z['name']:20s} ({cid:15s}) id={z['id']} -> {z['to']}")

    # Damage
    if eff['damage']:
        print(f"  Damage effects: {len(eff['damage'])}")
        for d in eff['damage'][:5]:
            print(f"    {d['name']:20s} id={d['id']} {d['tag']}={d['value']}")

    # Buffs
    if eff['buff']:
        print(f"  Buff effects: {len(eff['buff'])}")
        for d in eff['buff'][:5]:
            print(f"    {d['name']:20s} id={d['id']} {d['tag']}={d['value']}")

    # Stat sets
    if eff['stat_set']:
        print(f"  Stat set: {len(eff['stat_set'])}")
        for d in eff['stat_set'][:5]:
            print(f"    {d['name']:20s} id={d['id']} {d['tag']}={d['value']}")

    # Summons
    if eff['summons']:
        print(f"  Summons: {len(eff['summons'])}")
        for s in eff['summons'][:5]:
            print(f"    id={s['id']} card={s['card_id']}")

    # Meta
    print(f"  Nested PLAYs: {eff['child_plays_count']}, TRIGGERs: {eff['triggers_count']}, DEATHS: {eff['deaths_count']}")

    # Show important other tags
    important_tags = [t for t in eff['other_tag'] if t['tag'] in
                      ('EXHAUSTED', 'NUM_ATTACKS_THIS_TURN', 'TAUNT', 'DIVINE_SHIELD',
                       'POISONOUS', 'WINDFURY', 'CHARGE', 'RUSH', 'FROZEN',
                       'STEALTH', 'CANT_BE_TARGETED', 'IMMUNE', 'OVERLOAD',
                       'SPELLBURST', 'FRENZY', 'REBORN', 'LIFESTEAL',
                       'NUM_MINIONS_PLAYED_THIS_TURN', 'SPELLPOWER',
                       'AURA', 'ENRAGED', 'OUTCAST', 'CORRUPTED',
                       'QUEST_PROGRESS', 'SIDEKICK', 'FINALE',
                       'ATK_PRIORITY', 'COPIED_BY_KAZAKUS', 'INFUSE',
                       'HONORABLEKILL', 'LOCATION_COOLDOWN',
                       'ARMOR', 'TEMP_RESOURCES', 'RESOURCES_USED')]
    if important_tags:
        print(f"  Key tags:")
        for t in important_tags[:8]:
            print(f"    {t['name']:20s} id={t['id']} {t['tag']}={t['value']}")

    # Target info
    tgt = b['target']
    if tgt and tgt != '0 SubOption=-1' and tgt != '0 SubOption=1':
        tgt_ent = resolve_entity(tgt)
        print(f"  Target: {tgt_ent['name']} ({tgt_ent['card_id']}) id={tgt_ent['id']}")

    print()

# Also show ATTACK blocks
attack_blocks = [b for b in blocks if b['type'] == 'ATTACK']
print(f"\n=== ATTACK BLOCKS: {len(attack_blocks)} ===\n")
for b in attack_blocks[:15]:
    ent = resolve_entity(b['entity'])
    tgt = resolve_entity(b['target']) if b['target'] else {}
    print(f"L{b['line']:5d} {ent['name']:20s}({ent['card_id']:15s}) -> {tgt.get('name','?'):20s}({tgt.get('card_id',''):15s})")

# HERO_POWER blocks
hp_blocks = [b for b in blocks if b['type'] == 'HERO_POWER']
print(f"\n=== HERO_POWER BLOCKS: {len(hp_blocks)} ===\n")
for b in hp_blocks[:10]:
    ent = resolve_entity(b['entity'])
    tgt = resolve_entity(b['target']) if b['target'] else {}
    print(f"L{b['line']:5d} {ent['name']:20s}({ent['card_id']:15s}) -> {tgt.get('name','?'):20s}({tgt.get('card_id',''):15s})")

# TRIGGER-only top-level blocks (not inside PLAY)
print(f"\n=== STANDALONE TRIGGER BLOCKS (not inside PLAY): first 20 ===\n")
for b in blocks:
    if b['type'] == 'TRIGGER':
        ent = resolve_entity(b['entity'])
        eff_card = b['effect_card']
        if ent['card_id'] or eff_card:
            print(f"L{b['line']:5d} TRIGGER {ent['name']:20s}({ent['card_id'] or eff_card:15s}) player={ent['player']} target={b['target'][:60]}")
