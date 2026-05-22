#!/usr/bin/env python3
"""Parse Power.log to extract card play events and their effect chains."""
import re
import sys

log_file = sys.argv[1] if len(sys.argv) > 1 else 'Power.log'

with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

# Build entity -> cardId mapping
card_map = {}
for line in lines:
    m = re.match(r'.*FULL_ENTITY - Creating ID=(\d+) CardID=(\S+)', line)
    if m:
        eid, card_id = m.group(1), m.group(2)
        if card_id:
            card_map[int(eid)] = card_id

    m = re.match(r'.*SHOW_ENTITY - Updating EntityID=(\d+) CardID=(\S+)', line)
    if m:
        eid, card_id = m.group(1), m.group(2)
        if card_id:
            card_map[int(eid)] = card_id

# Parse tag changes for zone tracking
entity_zone = {}  # eid -> zone
entity_controller = {}  # eid -> controller
entity_cardtype = {}  # eid -> cardtype

for line in lines:
    m = re.match(r'.*TAG_CHANGE Entity=\[.*id=(\d+).*\] tag=(\w+) value=(\S+)', line)
    if not m:
        m = re.match(r'.*TAG_CHANGE Entity=\[id=(\d+).*\] tag=(\w+) value=(\S+)', line)
    if not m:
        m = re.match(r'.*TAG_CHANGE Entity=\[.*name=(\w+).*id=(\d+).*\] tag=(\w+) value=(\S+)', line)
    if m:
        if len(m.groups()) == 4:
            eid, tag, val = int(m.group(2)), m.group(3), m.group(4)
        else:
            eid, tag, val = int(m.group(1)), m.group(2), m.group(3)
        if tag == 'ZONE':
            entity_zone[eid] = val
        elif tag == 'CONTROLLER':
            entity_controller[eid] = val
        elif tag == 'CARDTYPE':
            entity_cardtype[eid] = val

# Parse blocks with nesting
blocks = []
block_stack = []

for i, line in enumerate(lines):
    if 'GameState.DebugPrintPower()' in line and 'BLOCK_START' in line:
        bt = re.search(r'BlockType=(\w+)', line)
        ent_raw = re.search(r'Entity=(.+?)\s*(?:EffectCardId|$)', line)
        eff = re.search(r'EffectCardId=(\S+)', line)
        et = re.search(r'EffectIndex=(-?\d+)', line)
        target = re.search(r'Target=(.+?)$', line)

        block_type = bt.group(1) if bt else '?'
        entity = ent_raw.group(1).strip() if ent_raw else ''
        # Remove trailing whitespace and 'EffectCardId' if captured
        entity = entity.replace('EffectCardId', '').strip()
        effect_card = eff.group(1) if eff else ''
        effect_idx = et.group(1) if et else ''
        tgt = target.group(1).strip() if target else ''

        block = {
            'type': block_type,
            'entity': entity,
            'entity_raw': line.strip(),
            'effect_card': effect_card,
            'effect_idx': effect_idx,
            'target': tgt,
            'line': i + 1,
            'children': [],
            'tag_changes': [],
        }

        if block_stack:
            block_stack[-1]['children'].append(block)
        else:
            blocks.append(block)
        block_stack.append(block)

    elif 'GameState.DebugPrintPower()' in line and 'BLOCK_END' in line:
        if block_stack:
            block_stack.pop()

    elif 'PowerTaskList.DebugPrintPower()' in line and 'BLOCK_START' in line:
        # PowerTaskList blocks - these contain the actual effects
        bt = re.search(r'BlockType=(\w+)', line)
        ent_raw = re.search(r'Entity=(.+?)\s*(?:EffectCardId|$)', line)
        eff = re.search(r'EffectCardId=(\S+)', line)
        et = re.search(r'EffectIndex=(-?\d+)', line)
        target = re.search(r'Target=(.+?)$', line)

        block_type = bt.group(1) if bt else '?'
        entity = ent_raw.group(1).strip() if ent_raw else ''
        entity = entity.replace('EffectCardId', '').strip()
        effect_card = eff.group(1) if eff else ''
        effect_idx = et.group(1) if et else ''
        tgt = target.group(1).strip() if target else ''

        block = {
            'type': block_type,
            'entity': entity,
            'entity_raw': line.strip(),
            'effect_card': effect_card,
            'effect_idx': effect_idx,
            'target': tgt,
            'line': i + 1,
            'children': [],
            'tag_changes': [],
        }

        if block_stack:
            block_stack[-1]['children'].append(block)
        else:
            blocks.append(block)
        block_stack.append(block)

    elif 'PowerTaskList.DebugPrintPower()' in line and 'BLOCK_END' in line:
        if block_stack:
            block_stack.pop()

# Also collect TAG_CHANGEs inside blocks for context
# Reset and re-parse with tag change tracking
block_stack2 = []
all_blocks_flat = []

for i, line in enumerate(lines):
    is_debug_power = 'GameState.DebugPrintPower()' in line
    is_task_power = 'PowerTaskList.DebugPrintPower()' in line

    if (is_debug_power or is_task_power) and 'BLOCK_START' in line:
        bt = re.search(r'BlockType=(\w+)', line)
        block_type = bt.group(1) if bt else '?'
        block_stack2.append({'type': block_type, 'line': i+1})
    elif (is_debug_power or is_task_power) and 'BLOCK_END' in line:
        if block_stack2:
            block_stack2.pop()

# Now extract PLAY card plays with their nested effects
print(f"Total card entities: {len(card_map)}")
print(f"Total top-level blocks: {len(blocks)}")
print()

# Find PLAY blocks
play_blocks = [b for b in blocks if b['type'] == 'PLAY']
print(f"=== PLAY CARD BLOCKS: {len(play_blocks)} ===\n")

for b in play_blocks:
    # Resolve card ID from entity string
    entity = b['entity']
    resolved_card = ''
    for eid, cid in card_map.items():
        if f'id={eid}' in entity or f'[{eid}]' in entity:
            resolved_card = cid
            break

    # Extract entity ID
    eid_m = re.search(r'id=(\d+)', entity)
    eid_val = eid_m.group(1) if eid_m else '?'

    print(f"--- PLAY at line {b['line']} ---")
    print(f"  Entity: {entity[:120]}")
    print(f"  CardID: {resolved_card or 'unknown'}")
    print(f"  Target: {b['target'][:80]}")

    # Show nested children
    def show_children(children, indent=2):
        for c in children:
            c_entity = c['entity']
            c_card = ''
            for eid, cid in card_map.items():
                if f'id={eid}' in c_entity:
                    c_card = cid
                    break
            print(f"{' '*indent}L{c['line']:5d} {c['type']:12s} card={c_card or c['effect_card'] or '?':20s} target={c['target'][:60]}")
            if c['children']:
                show_children(c['children'], indent + 2)

    show_children(b['children'])
    print()

# Also show TRIGGER blocks that aren't inside PLAY
print("\n=== TOP-LEVEL TRIGGER/ACTION/POWER BLOCKS ===\n")
trigger_blocks = [b for b in blocks if b['type'] in ('TRIGGER', 'ACTION', 'POWER')]
for b in trigger_blocks[:30]:  # first 30
    entity = b['entity']
    resolved_card = ''
    for eid, cid in card_map.items():
        if f'id={eid}' in entity:
            resolved_card = cid
            break
    print(f"L{b['line']:5d} {b['type']:12s} card={resolved_card or b['effect_card'] or '?':20s} entity={entity[:80]}")
