"""Determine current standard-legal sets using python-hearthstone."""
from hearthstone import cardxml
from hearthstone.enums import CardSet, CardType
from collections import Counter

print("Loading card database...")
db, _ = cardxml.load()
print(f"Total cards in DB: {len(db)}")

# Find all collectible cards and their sets
collectible = [c for c in db.values() if c.collectible]
print(f"Collectible cards: {len(collectible)}")

sets = Counter(c.card_set for c in collectible)
print("\n=== Collectible cards by CardSet enum ===")
for cs, cnt in sorted(sets.items(), key=lambda x: -x[1]):
    print(f"  {cs.name} ({cs.value}): {cnt}")

# Check if there's a way to determine standard sets
# In hearthstone package, CardSet enum has a 'standard' property or similar
print("\n=== Checking CardSet for standard flag ===")
for member in CardSet:
    if hasattr(member, 'standard'):
        print(f"  {member.name}: standard={member.standard}")

# Alternative: check from hearthstone.sslexecute_utils or similar
try:
    from hearthstone.utils import STANDARD_SETS
    print(f"\nSTANDARD_SETS: {STANDARD_SETS}")
except ImportError:
    pass

# Check CardSet member attributes
print("\n=== CardSet member attributes ===")
sample = CardSet.EMERALD_DREAM
print(f"EMERALD_DREAM: value={sample.value}, dir={[a for a in dir(sample) if not a.startswith('_')]}")
