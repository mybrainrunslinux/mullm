"""
Optional groundtruth category: gaming.

Covers general game development math and reference data:
  - 52-card deck encoding & poker hands
  - Dice probability (d6, d20, advantage/disadvantage)
  - Isometric & hexagonal grid math
  - RPG XP curves, loot tables, encounter balance
  - 3D rigging, UV, walk cycles

Extracted from oldcode/groundtruth_gaming.py.
Enable via mullm.toml: enabled_categories = [..., "gaming"]
"""
from __future__ import annotations

import re

from ..registry import CategoryPlugin, register_category

# ---------------------------------------------------------------------------
# Card deck facts
# ---------------------------------------------------------------------------

_CARD_FACTS = (
    "**52-Card Deck Reference**\n\n"
    "**card(n) encoding:** `rank = n % 13`, `suit = n // 13`\n\n"
    "```\nranks = ['2','3','4','5','6','7','8','9','10','J','Q','K','A']\n"
    "suits = ['spades','hearts','diamonds','clubs']  # 0=Spades 1=Hearts 2=Diamonds 3=Clubs\n"
    "card(n) = ranks[n % 13] + suits[n // 13]\n```\n\n"
    "**Key positions:** card(0)=2 spades  card(12)=A spades  card(13)=2 hearts  "
    "card(25)=A hearts  card(26)=2 diamonds  card(51)=A clubs\n\n"
    "**Fisher-Yates shuffle:** iterate `i` from `n-1` down to `1`, "
    "swap `arr[i]` with `arr[randint(0, i)]`\n\n"
    "**Poker hand ranks (high to low):**\n"
    "Royal Flush > Straight Flush > Four of a Kind > Full House > Flush > "
    "Straight > Three of a Kind > Two Pair > Pair > High Card\n\n"
    "**Blackjack basic strategy:** hit on hard <=16 vs dealer 7+; stand on hard 17+; "
    "always split Aces and 8s; never split 10s or 5s"
)

_CARDS_RE = re.compile(
    r"card.*\d+|\d+.*card|deck.*52|52.*card|fisher.yates|blackjack.*basic|poker.*hand",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dice probability
# ---------------------------------------------------------------------------

_DICE_FACTS = (
    "**Dice Probability Reference**\n\n"
    "**d6:** avg = 3.5, variance = 35/12 ~= 2.917\n\n"
    "**2d6 sums:**\n"
    "| Sum | Ways | Probability |\n"
    "|-----|------|-------------|\n"
    "| 2   | 1    | 1/36        |\n"
    "| 7   | 6    | 6/36 = 1/6  |\n"
    "| 12  | 1    | 1/36        |\n\n"
    "Most common sum = **7** (6 out of 36 outcomes)\n\n"
    "**d20:** avg = 10.5\n"
    "- Advantage (roll 2, take max): P(>=k) = 1 - (k-1)^2 / 400\n"
    "- Disadvantage (roll 2, take min): P(>=k) = (21-k)^2 / 400\n\n"
    "**Expected damage:** `base_damage x hit_chance`; crit doubles dice (NOT modifiers in D&D 5e)\n\n"
    "**XdY+Z notation:** roll X dice of Y sides, add Z modifier"
)

_DICE_RE = re.compile(
    r"dice.*prob|2d6|d20.*advantage|d6.*average|ttrpg.*dice|roll.*dice",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Isometric & Hexagonal Grid Math
# ---------------------------------------------------------------------------

_GRID_FACTS = (
    "**Isometric & Hexagonal Grid Math**\n\n"
    "**Isometric tile to screen:**\n"
    "```\nsx = (col - row) * tileWidth / 2\n"
    "sy = (col + row) * tileHeight / 2\n```\n\n"
    "**Screen to isometric tile:**\n"
    "```\ncol = (sx / tileWidth  + sy / tileHeight)\n"
    "row = (sy / tileHeight - sx / tileWidth)\n```\n\n"
    "**Axial hex coords (q, r) — 6 neighbors:**\n"
    "`[+1,0] [-1,0] [0,+1] [0,-1] [+1,-1] [-1,+1]`\n\n"
    "**Hex distance (axial):**\n"
    "```\ndist = max(|q1-q2|, |r1-r2|, |-q1-r1+q2+r2|)\n```\n\n"
    "**Ring at radius N:** N x 6 hexes\n"
    "**Spiral (all hexes within radius N):** 3N^2 + 3N + 1 hexes total"
)

_GRID_RE = re.compile(
    r"iso.*tile|isometric.*grid|hex.*grid|axial.*coord|hex.*neighbor|hex.*distance|tile.*screen",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# RPG & Game Design Math
# ---------------------------------------------------------------------------

_RPG_FACTS = (
    "**RPG & Game Design Math**\n\n"
    "**XP curves:**\n"
    "- Geometric: `xp(level) = base x ratio^level` — D&D 5e uses ~x2 per tier\n"
    "- Quadratic: `xp(level) = base x level^2`\n"
    "- Linear: `xp(level) = base x level`\n\n"
    "**Loot table weighted random:** normalize weights -> cumulative sum -> "
    "binary search random value in [0, 1)\n\n"
    "**Combat balance:**\n"
    "```\ndamage = base x (stat / 100)\n"
    "dodge  = 1 - (def_speed / (atk_speed + def_speed))\n```\n\n"
    "**Quest archetypes:** Fetch · Escort · Kill/Clear · Explore · Defend · Puzzle · Rescue · Deliver\n\n"
    "**Hero's Journey (Campbell 12 stages):**\n"
    "1-Ordinary World  2-Call to Adventure  3-Refusal  4-Meeting the Mentor  "
    "5-Crossing Threshold  6-Tests  7-Approach  8-Ordeal  "
    "9-Reward  10-Road Back  11-Resurrection  12-Return with Elixir"
)

_RPG_RE = re.compile(
    r"xp.*curve|loot.*table|combat.*balance|encounter.*balance|quest.*archetype|hero.*journey|rpg.*design",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Combined resolver
# ---------------------------------------------------------------------------

def _resolve_gaming(q: str) -> str | None:
    lower = q.lower()
    if _CARDS_RE.search(lower):
        return _CARD_FACTS
    if _DICE_RE.search(lower):
        return _DICE_FACTS
    if _GRID_RE.search(lower):
        return _GRID_FACTS
    if _RPG_RE.search(lower):
        return _RPG_FACTS
    return None


def register_gaming() -> None:
    register_category(CategoryPlugin(
        name="gaming",
        patterns=[],
        resolver=_resolve_gaming,
    ))
