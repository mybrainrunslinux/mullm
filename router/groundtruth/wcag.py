"""
Groundtruth WCAG 2.2 accessibility category.

Covers: contrast ratios, touch targets, focus indicators, ARIA, animation,
color independence, and new-in-2.2 success criteria.

Extracted from oldcode/groundtruth_design.py.
"""
from __future__ import annotations

import re

from .registry import CategoryPlugin, register_category

# ---------------------------------------------------------------------------
# WCAG topic strings
# ---------------------------------------------------------------------------

_WCAG_TOPICS: dict[str, str] = {
    "contrast": (
        "**WCAG 2.2 AA Contrast Ratios**\n\n"
        "| Text type                          | Minimum ratio |\n"
        "|------------------------------------|---------------|\n"
        "| Normal text (<18pt / <14pt bold)   | 4.5:1         |\n"
        "| Large text (>=18pt or >=14pt bold) | 3:1           |\n"
        "| UI components & graphics           | 3:1           |\n"
        "| Incidental / decorative            | No requirement |\n\n"
        "**Relative luminance formula**: L = 0.2126R + 0.7152G + 0.0722B (linearized sRGB)\n\n"
        "**Contrast ratio** = (L_lighter + 0.05) / (L_darker + 0.05)\n\n"
        "AAA enhanced thresholds: 7:1 normal text, 4.5:1 large text.\n\n"
        "Tools: axe DevTools, Chrome Lighthouse, WebAIM Contrast Checker."
    ),
    "focus": (
        "**WCAG 2.2 Focus Indicators** (SC 2.4.7, 2.4.11, 2.4.12)\n\n"
        "- Visible focus ring required for all interactive elements (AA: 2.4.7)\n"
        "- **2.4.11 Focus Appearance (Min, AA new in 2.2)**: focus indicator must have area "
        ">= perimeter of component x 2px CSS, and contrast >= 3:1 between focused/unfocused states\n"
        "- **2.4.12 Focus Appearance (Enhanced, AAA)**: focus ring >= 3px, contrast >= 4.5:1\n\n"
        "Best practice CSS:\n"
        "```css\n"
        ":focus-visible {\n"
        "  outline: 3px solid #005fcc;\n"
        "  outline-offset: 2px;\n"
        "  border-radius: 2px;\n"
        "}\n"
        ":focus:not(:focus-visible) { outline: none; }  /* hide on mouse click only */\n"
        "```\n\n"
        "Never use `outline: none` without a replacement visible indicator."
    ),
    "touch": (
        "**WCAG 2.2 Touch Targets** (SC 2.5.5, 2.5.8)\n\n"
        "| Level | Criterion          | Minimum size              |\n"
        "|-------|-------------------|---------------------------|\n"
        "| AA    | 2.5.8 (new in 2.2) | 24x24 px minimum (with spacing) |\n"
        "| AAA   | 2.5.5              | 44x44 px                  |\n\n"
        "- Exception: inline links in text, form labels, and other inline elements\n"
        "- If target is <24px, spacing around it must compensate so nothing overlaps a 24px circle\n"
        "- iOS HIG recommends 44x44 pt; Android recommends 48x48 dp"
    ),
    "animation": (
        "**WCAG 2.2 Animation Rules** (SC 2.2.2, 2.3.1, 2.3.3)\n\n"
        "- **2.3.1 (AA)**: NEVER flash content more than 3 times per second\n"
        "- **2.3.3 (AAA)**: Provide a way to disable all non-essential animation\n"
        "- **prefers-reduced-motion**: Always implement\n\n"
        "```css\n"
        "@media (prefers-reduced-motion: reduce) {\n"
        "  *, *::before, *::after {\n"
        "    animation-duration: 0.01ms !important;\n"
        "    animation-iteration-count: 1 !important;\n"
        "    transition-duration: 0.01ms !important;\n"
        "    scroll-behavior: auto !important;\n"
        "  }\n"
        "}\n"
        "```\n\n"
        "Safe animations: opacity fade, subtle translate <=12px. Unsafe: spinning, flashing, parallax."
    ),
    "color independence": (
        "**WCAG 2.2 Color Independence** (SC 1.4.1 AA)\n\n"
        "NEVER use color as the ONLY visual means of conveying information.\n\n"
        "Always pair color with at least ONE of:\n"
        "- **Pattern or texture** (e.g. striped vs solid chart bars)\n"
        "- **Icon or symbol** (check/x/warning for success/error/warning)\n"
        "- **Text label** ('Success', 'Error', 'Warning')\n"
        "- **Shape** (different chart marker shapes per series)\n\n"
        "Red-green colorblindness affects ~8% of men. Safe palette: blue-orange instead of red-green."
    ),
    "aria": (
        "**WCAG 2.2 ARIA & Semantic HTML** (SC 4.1.2 AA)\n\n"
        "**Rule 1**: Use native semantic HTML before ARIA.\n"
        "- `<button>` not `<div role=button>`\n"
        "- `<nav>` not `<div role=navigation>`\n"
        "- `<main>`, `<header>`, `<footer>`, `<section>`, `<article>` for landmarks\n\n"
        "**Common ARIA attributes**:\n"
        "```html\n"
        '<button aria-label="Close dialog">x</button>   <!-- icon-only button -->\n'
        '<div role="status" aria-live="polite">Saved</div>  <!-- live region -->\n'
        '<img src="deco.png" alt="">                   <!-- decorative: empty alt -->\n'
        '<nav aria-label="Main navigation">...</nav>   <!-- distinguish multiple navs -->\n'
        "```\n\n"
        "**Heading hierarchy**: never skip levels. h1->h2->h3, not h1->h3.\n\n"
        "**Screen reader testing**: NVDA+Firefox, VoiceOver+Safari, JAWS+Chrome."
    ),
    "new in 2.2": (
        "**WCAG 2.2 — New Success Criteria vs 2.1**\n\n"
        "| SC       | Name                         | Level | Summary                                       |\n"
        "|----------|------------------------------|-------|-----------------------------------------------|\n"
        "| 2.4.11   | Focus Appearance (Min)       | AA    | Focus indicator area + 3:1 contrast required  |\n"
        "| 2.4.12   | Focus Appearance (Enhanced)  | AAA   | >=3px focus ring, >=4.5:1 contrast            |\n"
        "| 2.5.7    | Dragging Movements           | AA    | All drag actions need a pointer alternative    |\n"
        "| 2.5.8    | Target Size (Min)            | AA    | Touch targets >=24x24 px (with spacing)       |\n"
        "| 3.2.6    | Consistent Help              | AA    | Help mechanisms in consistent location        |\n"
        "| 3.3.7    | Redundant Entry              | AA    | Don't ask for same info twice in one session  |\n"
        "| 3.3.8    | Accessible Authentication    | AA    | No cognitive function test to log in          |\n\n"
        "Removed from 2.2: 4.1.1 Parsing (deprecated)."
    ),
}

_WCAG_RE = re.compile(
    r"\bwcag\b|\bwcag\s*2\.2\b|"
    r"\bcontrast\s*ratio\b|\baria.label\b|\bscreen\s*reader\b|"
    r"\bfocus\s*indicator\b|\btouch\s*target\b|"
    r"\bprefers.reduced.motion\b|\baccessibility\s*standard\b",
    re.IGNORECASE,
)


def _resolve_wcag(q: str) -> str | None:
    lower = q.lower()
    if not _WCAG_RE.search(lower):
        return None

    if re.search(r"\bnew\s+(?:in|criteria?|sc)?\s*2\.2\b|\b2\.2\s+new\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["new in 2.2"]
    if re.search(r"\bfocus\s*(?:ring|indicator|appear|visible)\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["focus"]
    if re.search(r"\btouch\s*target\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["touch"]
    if re.search(r"\bprefers.reduced.motion\b|\banimation\b.*\bwcag\b|\bwcag\b.*\banimation\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["animation"]
    if re.search(r"\bcolor\s*(?:only|independence|alone)\b|\bcolorblind\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["color independence"]
    if re.search(r"\baria\b|\bscreen\s*reader\b|\bsemantic\s*html\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["aria"]
    if re.search(r"\bcontrast\s*ratio\b|\bcontrast\b", lower, re.IGNORECASE):
        return _WCAG_TOPICS["contrast"]

    return _WCAG_TOPICS["contrast"]


def register_wcag() -> None:
    register_category(CategoryPlugin(
        name="wcag",
        patterns=[],
        resolver=_resolve_wcag,
    ))
