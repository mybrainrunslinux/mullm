"""Game market research API — powered by local mullm LLM.

Endpoints mount at /api/market and provide structured gamedev market intelligence:
  GET  /api/market/report       — full market research report for a concept
  POST /api/market/analyze      — TAM, comparable revenue, risks, platforms
  POST /api/market/steam-timing — optimal Steam release window analysis
  POST /api/market/competitors  — similar games with estimated performance
  POST /api/market/pivot        — honest pivot-or-proceed recommendation
  POST /api/market/qa           — quality gate: is this game ready to ship?

All endpoints call the local mullm query endpoint at http://127.0.0.1:6856/query.
Timeout is generous (120s) — local 30B inference can be slow.
"""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger("mullm.market")

router = APIRouter(prefix="/api/market", tags=["market"])

# ---------------------------------------------------------------------------
# Internal LLM client
# ---------------------------------------------------------------------------

MULLM_QUERY_URL = "http://127.0.0.1:6856/query"
LLM_TIMEOUT = 120.0  # seconds — local 30B can be slow


async def _ask_llm(prompt: str) -> str:
    """POST a prompt to the local mullm query endpoint, return the response text."""
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            resp = await client.post(
                MULLM_QUERY_URL,
                json={"content": prompt},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            return str(data.get("response", data.get("content", "")))
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail="Local mullm LLM is not reachable at 127.0.0.1:6856. "
                   "Start it with: python -m router.main",
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Local LLM timed out after 120s. The model may be loading — try again.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Local LLM returned HTTP {exc.response.status_code}: {exc.response.text[:200]}",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local mullm LLM request failed: {exc.__class__.__name__}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error calling local LLM")
        raise HTTPException(status_code=500, detail=f"LLM call failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

BudgetTier = str  # "indie_solo" | "indie_small" | "indie_funded" | "aa" | "aaa"
Platform = str    # "pc" | "android" | "ios" | "switch" | "ps5" | "xbox"


class GameConcept(BaseModel):
    concept: str = Field(..., min_length=10, max_length=2000,
                         description="Elevator pitch or description of the game concept")
    title: str = Field(default="", max_length=200, description="Working title")
    genre: list[str] = Field(default_factory=list, max_length=10,
                             description="Genre tags, e.g. ['roguelike', 'deckbuilder']")
    target_platforms: list[Platform] = Field(default_factory=lambda: ["pc"],
                                              max_length=6)
    budget: BudgetTier = Field(default="indie_solo",
                                description="Budget tier: indie_solo / indie_small / indie_funded / aa / aaa")
    similar_games: list[str] = Field(default_factory=list, max_length=20,
                                      description="Known comparable games, e.g. ['Slay the Spire', 'Monster Train']")
    target_price_usd: float = Field(default=14.99, ge=0.0, le=999.0,
                                     description="Intended Steam/App Store price in USD")
    development_months_remaining: int = Field(default=12, ge=0, le=120,
                                               description="Estimated months until launch")


class TimingRequest(BaseModel):
    concept: str = Field(..., min_length=5, max_length=1000)
    genre: list[str] = Field(default_factory=list)
    target_platforms: list[Platform] = Field(default_factory=lambda: ["pc"])
    budget: BudgetTier = Field(default="indie_solo")
    development_months_remaining: int = Field(default=12, ge=0, le=120)


class CompetitorRequest(BaseModel):
    concept: str = Field(..., min_length=5, max_length=1000)
    genre: list[str] = Field(default_factory=list)
    similar_games: list[str] = Field(default_factory=list, max_length=20)
    target_platforms: list[Platform] = Field(default_factory=lambda: ["pc"])
    target_price_usd: float = Field(default=14.99, ge=0.0, le=999.0)


class PivotRequest(BaseModel):
    concept: str = Field(..., min_length=10, max_length=2000)
    genre: list[str] = Field(default_factory=list)
    budget: BudgetTier = Field(default="indie_solo")
    development_months_remaining: int = Field(default=12, ge=0, le=120)
    pain_points: str = Field(default="", max_length=1000,
                              description="Current concerns prompting the pivot question")
    similar_games: list[str] = Field(default_factory=list, max_length=20)


class QARequest(BaseModel):
    concept: str = Field(..., min_length=10, max_length=2000)
    genre: list[str] = Field(default_factory=list)
    target_platforms: list[Platform] = Field(default_factory=lambda: ["pc"])
    target_price_usd: float = Field(default=14.99, ge=0.0, le=999.0)
    game_length_hours: float = Field(default=10.0, ge=0.0, le=10000.0,
                                      description="Expected average playtime in hours")
    has_multiplayer: bool = Field(default=False)
    is_early_access: bool = Field(default=False)
    content_warnings: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Prompt builders — substantive, gamedev-specific
# ---------------------------------------------------------------------------

def _budget_label(budget: BudgetTier) -> str:
    labels = {
        "indie_solo": "solo indie dev (no salary, <$10K hard costs)",
        "indie_small": "small indie team (2–5 people, <$100K)",
        "indie_funded": "funded indie (>$100K, publisher or grant-backed)",
        "aa": "AA studio (>$1M budget)",
        "aaa": "AAA studio (>$10M budget)",
    }
    return labels.get(budget, budget)


def _build_analyze_prompt(req: GameConcept) -> str:
    genres = ", ".join(req.genre) if req.genre else "not specified"
    platforms = ", ".join(req.target_platforms)
    comparables = ", ".join(req.similar_games) if req.similar_games else "none specified"
    budget_desc = _budget_label(req.budget)
    title_line = f'Working title: "{req.title}"\n' if req.title else ""

    return f"""You are a senior game industry market analyst with 15+ years of experience analyzing indie and AA game releases on Steam, mobile, and console platforms.

Analyze this game concept and return a structured market research report. Be specific with numbers — cite actual revenue ranges from real comparable games, not vague estimates. If you don't know a specific number, give a realistic range and explain your reasoning.

GAME CONCEPT:
{title_line}Concept: {req.concept}
Genre: {genres}
Target platforms: {platforms}
Budget tier: {budget_desc}
Price point: ${req.target_price_usd:.2f} USD
Months until launch: {req.development_months_remaining}
Known comparables: {comparables}

REQUIRED ANALYSIS SECTIONS:

1. MARKET SIZE & TAM
- Global TAM for this genre/platform combination (Steam PC games in this genre)
- Realistic Serviceable Addressable Market (SAM) for an indie title in this niche
- What % of the TAM a solo/small indie can realistically capture in year 1
- Genre growth trends: is this genre growing, peaking, or saturating?

2. COMPARABLE GAME REVENUE
For 3–5 real comparable games (ideally from the genres/games mentioned), estimate:
- Approximate units sold in first year (use SteamSpy estimates or known data)
- Approximate gross revenue (units × price, before platform cut)
- Net revenue after 30% platform cut and typical 15% refund rate
- What % were "hits" vs "quiet successes" vs "commercial disappointments"

3. REVENUE PROJECTIONS
Based on comparable data, project realistic scenarios:
- Pessimistic case (20th percentile): units sold, revenue
- Base case (50th percentile): units sold, revenue
- Optimistic case (80th percentile): units sold, revenue
- What would "break-even" look like at this budget tier?

4. KEY RISKS
List the top 5 risks in order of severity, with likelihood (Low/Medium/High) and impact (Low/Medium/High):
- Market risks (genre saturation, timing, platform changes)
- Execution risks (scope, polish, content depth)
- Distribution risks (Steam algorithm, visibility, marketing budget)
- Competitive risks (similar games launching near your window)

5. PLATFORM RECOMMENDATIONS
For each target platform ({platforms}):
- Fit score (1–10) for this genre
- Typical revenue split vs effort required
- Specific considerations for this genre on this platform

6. POSITIONING RECOMMENDATION
- What is the unique hook that differentiates this from {comparables if comparables != 'none specified' else 'existing games in the genre'}?
- What tag/keyword positioning would maximize Steam visibility?
- What price point is optimal and why?

Be direct and honest. If this concept has fundamental market problems, say so clearly.
Return your analysis in clean sections with headers. Use specific numbers wherever possible."""


def _build_timing_prompt(req: TimingRequest) -> str:
    genres = ", ".join(req.genre) if req.genre else "not specified"
    platforms = ", ".join(req.target_platforms)
    budget_desc = _budget_label(req.budget)

    return f"""You are a Steam release strategy expert who has analyzed thousands of indie game launches. Your job is to give honest, specific advice about WHEN to release this game for maximum visibility and revenue.

GAME CONTEXT:
Concept: {req.concept}
Genre: {genres}
Platforms: {platforms}
Budget tier: {budget_desc}
Development time remaining: {req.development_months_remaining} months

Answer each section with specific dates, not vague advice:

1. STEAM NEXT FEST (Steam Game Festival) TIMING
- When are the upcoming Steam Next Fests? (typically February, June, October — give approximate dates for the next 18 months)
- Should this game target a Next Fest demo before launch? Why or why not?
- For {genres} games specifically, what is the typical wishlist conversion from Next Fest demos?
- How many months before launch should the Steam page go live to maximize wishlist accumulation?

2. RELEASE WINDOW ANALYSIS
- What are the best calendar windows for a {genres} indie game in the next 18 months?
- What windows to AVOID: holidays (December is brutal for indie visibility), major AAA release dates, gaming events that dominate press attention
- Is there a "sweet spot" quarter where {genres} games historically perform better?
- What day of the week should the game launch? (Tuesday–Thursday are typically best — explain why)

3. STEAM ALGORITHM CONSIDERATIONS
- How many wishlists does this genre typically need before launch to get algorithm visibility?
- What is the "launch momentum window" — how many sales in the first 24/48 hours matter most to Steam's algorithm?
- How does Early Access timing differ from full launch timing for this genre?
- What review velocity matters for the algorithm (getting to 10, 50, 500 reviews)?

4. GENRE SATURATION CALENDAR
- Are there specific months when the market floods with {genres} games? (e.g., post-game-jam releases)
- What is the current saturation level in this genre on Steam?
- Are there underserved time windows when this genre gets less competition?

5. PLATFORM-SPECIFIC TIMING
For each platform ({platforms}):
- Any platform holder certification deadlines or submission windows to be aware of?
- Holiday vs non-holiday considerations specific to this platform's audience
- Simultaneous vs staggered launch recommendation

6. SPECIFIC RECOMMENDATION
Given {req.development_months_remaining} months of development remaining:
- What is the IDEAL launch date range (e.g., "early March 2026 to mid-April 2026")?
- What is the Steam page live date target?
- What is the Next Fest participation plan?
- What is the backup window if development slips?

Be specific with dates and numbers. Vague advice is useless."""


def _build_competitors_prompt(req: CompetitorRequest) -> str:
    genres = ", ".join(req.genre) if req.genre else "not specified"
    platforms = ", ".join(req.target_platforms)
    known = ", ".join(req.similar_games) if req.similar_games else "none provided — identify them yourself"

    return f"""You are a competitive intelligence analyst specializing in the indie game market. Your job is to map the competitive landscape for this game concept with real data.

GAME CONTEXT:
Concept: {req.concept}
Genre: {genres}
Platforms: {platforms}
Target price: ${req.target_price_usd:.2f}
Known comparables: {known}

REQUIRED ANALYSIS:

1. DIRECT COMPETITORS (5–8 games)
For each competitor, provide:
- Game name and developer
- Release date and current price
- Approximate copies sold (SteamSpy estimate or known data)
- Approximate revenue (lifetime, using copies × price with 30% platform cut)
- Steam review count and score (if known)
- What they do BETTER than most games in the genre
- What weakness or gap they leave for a new entrant

2. INDIRECT COMPETITORS
Games that compete for the same player's time/money but in adjacent genres. What are the top 3, and why do players choose them over direct genre games?

3. MARKET GAP ANALYSIS
Based on the competitor landscape:
- What specific features or experiences are players asking for that existing games don't deliver? (Base this on known community feedback, subreddits, Steam reviews of competitors)
- What price tier is underserved?
- What platform is underserved for this genre?

4. COMPETITIVE MOATS
For this specific concept, what could provide a sustainable competitive advantage?
- Mechanical novelty: what has NOT been done in this genre?
- Content depth vs breadth tradeoffs competitors got wrong
- Art style or aesthetic niche that's open
- Community/meta-game elements (speedrunning, modding, streaming-friendly)

5. THREAT ASSESSMENT
- Are any major studios (indie or AA) known to be working in this genre space right now?
- What Kickstarters or announced games might compete at launch?
- What is the risk of being "clone-shadowed" (a bigger studio copying your mechanic)?

6. REVENUE BENCHMARK TABLE
Create a realistic comparison table:
| Game | Price | Est. Units (Year 1) | Est. Revenue (Year 1) | Review Score |
|------|-------|---------------------|----------------------|--------------|
[fill in 5 rows with real games]

7. POSITIONING VERDICT
Given this competitive landscape, is there a viable market position for this concept?
- Green: clear gap exists, strong differentiation possible
- Yellow: crowded but winnable with strong execution
- Red: oversaturated, differentiation extremely difficult
State the verdict and explain."""


def _build_pivot_prompt(req: PivotRequest) -> str:
    genres = ", ".join(req.genre) if req.genre else "not specified"
    budget_desc = _budget_label(req.budget)
    comparables = ", ".join(req.similar_games) if req.similar_games else "none specified"
    pain = req.pain_points if req.pain_points else "not specified"

    return f"""You are a brutally honest game development consultant. A developer is asking you whether they should PIVOT their game concept or continue on the current path. This is a high-stakes question — give honest, direct advice even if it's painful. Do not be diplomatic when honesty is more useful.

CURRENT CONCEPT:
{req.concept}

Genre: {genres}
Budget: {budget_desc}
Development time remaining: {req.development_months_remaining} months
Known comparables: {comparables}
Pain points / concerns prompting this question: {pain}

ANALYSIS REQUIRED:

1. PIVOT PRESSURE SIGNALS
Which of these signals apply to the current concept? Rate each as None / Weak / Strong:
- Genre is overcrowded with no clear differentiation
- Development timeline is unrealistic for the scope
- Budget is insufficient to reach quality bar needed to compete
- Core mechanic is derivative (not novel enough to matter)
- Target audience is too small to be commercially viable
- Similar game just launched and captured the market
- Concept requires technical scope beyond the team's capability
- Price point is not supported by the content depth

2. CORE CONCEPT ASSESSMENT
- What is genuinely GOOD about this concept that's worth preserving?
- What is genuinely WEAK that a pivot might fix?
- Is the problem the concept itself, or execution/scope/resources?

3. PIVOT OPTIONS (if warranted)
If a pivot is recommended, provide 3 concrete directions ranked by viability:
Option A: Minimal pivot — keep core mechanic, change setting/theme/genre layer
Option B: Moderate pivot — restructure scope to fit budget, cut features aggressively
Option C: Major pivot — fundamentally different concept that uses transferable assets/skills

For each option:
- What exactly changes vs. the current plan
- Development time and cost impact
- Market opportunity vs. current path
- Risk: what could go wrong with this pivot

4. STAY-THE-COURSE CASE
Make the strongest possible argument for NOT pivoting:
- What would need to be true for the current concept to succeed commercially?
- What specific milestones would validate that staying is correct?
- What is the minimum viable version that could test market fit in 3–6 months?

5. PIVOT VERDICT
Give a clear recommendation:
- PIVOT (and which option): reason in 2–3 sentences
- STAY (with conditions): what must change to make staying viable
- UNCERTAIN (what data would resolve it): specific experiments to run

Be direct. Developers asking this question need real guidance, not hedging."""


def _build_qa_prompt(req: QARequest) -> str:
    genres = ", ".join(req.genre) if req.genre else "not specified"
    platforms = ", ".join(req.target_platforms)
    multiplayer_line = "Has multiplayer" if req.has_multiplayer else "Single-player only"
    early_access_line = "Planned as Early Access launch" if req.is_early_access else "Full release"
    warnings_line = f"Content warnings: {req.content_warnings}" if req.content_warnings else "No content warnings specified"

    return f"""You are a senior game producer and quality gate reviewer. Your job is to give a PASS/CONDITIONAL PASS/FAIL verdict on whether this game concept is ready to ship — or what it would need to reach that bar. Be brutally honest. Developers who ship an unready game do lasting damage to their brand.

GAME BEING EVALUATED:
Concept: {req.concept}
Genre: {genres}
Platforms: {platforms}
Price: ${req.target_price_usd:.2f}
Expected playtime: {req.game_length_hours:.0f} hours
{multiplayer_line}
{early_access_line}
{warnings_line}

QUALITY GATE CHECKLIST — evaluate each dimension:

1. VALUE PROPOSITION vs PRICE POINT
- At ${req.target_price_usd:.2f}, what is the expected content depth? ({req.game_length_hours:.0f}h playtime — is this appropriate?)
- Industry benchmark: $1 per hour is a common player heuristic. At ${req.target_price_usd:.2f}, players expect ≥{req.target_price_usd:.0f}h of content (or equivalent replay value). Does this concept deliver?
- What would players say in negative reviews about "not worth $XX"?
- Is there a more appropriate price point given the content scope?

2. VISUAL QUALITY vs MARKET EXPECTATIONS
- For {genres} at ${req.target_price_usd:.2f} on {platforms}, what is the minimum visual quality bar in 2025?
- What are the specific art/visual risks that would cause screenshot-based rejection?
- Capsule image and screenshot quality — can this game compete on the store page thumbnail alone?

3. GAMEPLAY DEPTH & REPLAYABILITY
- What is the replayability model for {genres}? Does this concept have it?
- How does this compare to top-rated games in the genre for depth of systems?
- What is the "one more run" or "one more hour" hook? Is it present?

4. NEGATIVE REVIEW RISKS
List the top 5 specific things that would cause negative Steam/App Store reviews:
- Content-related (too short, too easy, lack of content)
- Technical (performance, crashes, save issues)
- Design (UI/UX, tutorial, control issues)
- Value (price vs content mismatch)
- Genre expectation mismatch (not what players expected from the genre)

5. STOREFRONT REJECTION RISKS
- Steam: what would cause rejection by Valve's review team?
- Other platforms ({platforms}): specific platform requirements or typical rejection reasons for this genre
- Content rating implications for {warnings_line.lower()}
- Asset quality floor — what would fail Steam's basic quality review?

6. ACCESSIBILITY & WISHLIST APPEAL
- Does the concept have a clear "elevator pitch" in 15 words or less?
- Would the Steam capsule image communicate the genre and hook immediately?
- What is the key marketing moment or GIF that would make this go viral?

7. LAUNCH READINESS VERDICT
Based on the above:
- PASS: Ready to ship — specific strengths that justify confidence
- CONDITIONAL PASS: Ship with these specific changes (list them)
- FAIL: Not ready — here is what must be built/fixed before launch (specific list)

For CONDITIONAL PASS or FAIL: rank the required changes by player impact, not development cost."""


def _build_report_prompt(concept: str) -> str:
    return f"""You are a senior game industry analyst producing a comprehensive market research report for an independent game developer. This report should be actionable and specific — not generic advice.

GAME CONCEPT: {concept}

Generate a COMPLETE MARKET RESEARCH REPORT with the following sections. Use real data where available. Be specific with numbers and dates.

---
# GAME MARKET RESEARCH REPORT

## Executive Summary
(3–5 sentences: market opportunity, key risks, overall recommendation)

## Market Analysis
- Genre and platform market size
- Growth trends
- Current saturation level
- Addressable market for an indie title

## Competitive Landscape
- 5 direct competitors with estimated revenue
- Key differentiators and gaps in the market
- Competitive positioning recommendation

## Revenue Projections
- Pessimistic / Base / Optimistic scenarios
- Break-even analysis
- Year 1 and Year 3 projections

## Release Strategy
- Optimal launch window
- Steam Next Fest timing
- Platform priorities
- Pricing strategy

## Risk Assessment
- Top 5 risks with likelihood and impact ratings
- Mitigation strategies

## Quality Bar
- What this game needs to compete successfully
- Common pitfalls for this genre to avoid
- Minimum viable feature set for launch

## Recommendation
- Clear go/no-go signal
- If go: priority order of what to build
- If no-go: what would change the calculus

---
Write the full report now. Be direct and specific."""


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/report")
async def get_report(concept: str = "") -> JSONResponse:
    """Generate a full market research report for a game concept (passed as query param)."""
    if not concept or len(concept.strip()) < 10:
        return JSONResponse(
            {
                "status": "requires_concept",
                "detail": "Pass concept=<10+ character game concept> to generate a market report.",
            }
        )
    prompt = _build_report_prompt(concept.strip())
    text = await _ask_llm(prompt)
    return JSONResponse({"report": text, "concept": concept})


@router.post("/analyze")
async def analyze_concept(req: GameConcept) -> JSONResponse:
    """Full market analysis: TAM, revenue projections, risks, platform fit."""
    prompt = _build_analyze_prompt(req)
    text = await _ask_llm(prompt)
    return JSONResponse({
        "analysis": text,
        "concept": req.concept,
        "genre": req.genre,
        "platforms": req.target_platforms,
        "budget": req.budget,
        "price_usd": req.target_price_usd,
    })


@router.post("/steam-timing")
async def steam_timing(req: TimingRequest) -> JSONResponse:
    """Optimal timing for Steam page, Next Fest participation, and launch window."""
    prompt = _build_timing_prompt(req)
    text = await _ask_llm(prompt)
    return JSONResponse({
        "timing_analysis": text,
        "concept": req.concept,
        "months_remaining": req.development_months_remaining,
    })


@router.post("/competitors")
async def find_competitors(req: CompetitorRequest) -> JSONResponse:
    """Identify similar games, estimate their revenue, map the competitive landscape."""
    prompt = _build_competitors_prompt(req)
    text = await _ask_llm(prompt)
    return JSONResponse({
        "competitor_analysis": text,
        "genre": req.genre,
        "known_comparables": req.similar_games,
    })


@router.post("/pivot")
async def pivot_analysis(req: PivotRequest) -> JSONResponse:
    """Honest pivot-or-proceed recommendation with concrete pivot options."""
    prompt = _build_pivot_prompt(req)
    text = await _ask_llm(prompt)
    return JSONResponse({
        "pivot_analysis": text,
        "concept": req.concept,
        "pain_points": req.pain_points,
    })


@router.post("/qa")
async def quality_gate(req: QARequest) -> JSONResponse:
    """Quality gate: is this game good enough to ship? PASS / CONDITIONAL / FAIL verdict."""
    prompt = _build_qa_prompt(req)
    text = await _ask_llm(prompt)
    return JSONResponse({
        "qa_report": text,
        "concept": req.concept,
        "price_usd": req.target_price_usd,
        "playtime_hours": req.game_length_hours,
    })
