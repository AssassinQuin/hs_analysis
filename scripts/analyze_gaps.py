"""Quick analysis of sub-model coverage gaps."""
import json
import re
from collections import Counter

with open("hs_cards/hsjson_standard.json", "r", encoding="utf-8") as f:
    data = json.load(f)
cards = data["cards"]

# The 6 uncategorized cards
uncategorized_names = ["背刺", "生而平等", "眩晕", "亡者大军", "裂解术", "阿玛拉的故事"]

print("=== 6 truly uncategorized cards ===")
for card in cards:
    name = card.get("name", "")
    if name in uncategorized_names:
        text = re.sub(r"<[^>]+>", "", card.get("text", "") or "")
        cost = card.get("cost", 0)
        ctype = card.get("type", "")
        cclass = card.get("cardClass", "")
        mechs = card.get("mechanics", [])
        print(f"  {name} ({cost}mana {ctype} {cclass})")
        print(f"    text: {text[:120]}")
        print(f"    mechanics: {mechs}")
        print()

# Categories NOT in any sub-model
not_in_submodel = {
    "draw", "conditional_mana", "conditional_if", "conditional_per",
    "choose_one", "choose_one_mech", "vanilla_minion", "enchant",
    "transform", "shuffle", "tradeable_text", "tradeable_kw",
    "poisonous", "stealth", "spell_damage_text",
    "fixed_armor", "outcast", "hero_card", "corrupt",
}

print("=== Categories NOT mapped to any sub-model (6 sub-models A-F) ===")
for c in sorted(not_in_submodel):
    print(f"  {c}")
print()
print("Cards with ONLY these categories = deterministic effects")
print("V2 card model handles them directly (no EV modeling needed)")
print()

# Count how many cards have effects from each sub-model
submodel_cats = {
    "A": {"fixed_summon","random_summon","fixed_buff","random_buff","fixed_destroy","fixed_damage","taunt","rush","charge","divine_shield","aura","adjacent","colossal","reborn","fission","lineage","weapon_equip","weapon_type","copy_effect","fixed_heal","lifesteal"},
    "B": {"fixed_damage","random_damage","fixed_destroy","steal_effect","silence_effect","freeze_effect","secret","secret_text","discard","cant_attack"},
    "C": {"weapon_equip","weapon_type","location","dormant","aura","secret","secret_text","end_of_turn","start_of_turn","quest_text","reward","overload","immune_kw","immune_text","hero_card","cant_attack","windfury"},
    "D": {"deathrattle","random_summon","random_damage","random_generate","random_buff","dark_gift","battlecry","spellburst","frenzy","overheal","honorable_kill","omen","rewind","corrupt","conditional_when"},
    "E": {"quest_text","discover","reward"},
    "F": {"discover","dark_gift","random_summon","random_generate","random_buff","omen","rewind","imbue_text"},
}

# Check: which important categories are NOT in any sub-model?
all_covered = set()
for cats in submodel_cats.values():
    all_covered |= cats

important_uncovered = {
    "draw", "conditional_mana", "conditional_if", "conditional_per",
    "choose_one", "choose_one_mech", "vanilla_minion", "enchant",
    "transform", "shuffle", "fixed_armor", "outcast", "stealth",
    "spell_damage_text", "tradeable_text", "tradeable_kw",
}

print("=== Missing sub-model mappings (IMPORTANT) ===")
for cat in sorted(important_uncovered):
    print(f"  {cat} → should map to which sub-model?")

print()
print("=== Suggested sub-model expansions ===")
print("A (Board State) should ADD: vanilla_minion, draw (hand state), enchant, transform")
print("B (Opponent Threat) should ADD: transform (enemy transform)")
print("C (Lingering Effects) should ADD: conditional_mana (cross-turn mana), tradeable, outcast")
print("D (Trigger Probability) should ADD: conditional_if, conditional_per")
print("F (Card Pool) should ADD: choose_one (choice pool evaluation)")
print()
print("After expansion, most of the 74 'uncovered' cards would be covered.")
print("Remaining truly uncovered = pure vanilla minions + basic draw spells")
print("These are handled by V2 card model L1+L2 static scores.")
