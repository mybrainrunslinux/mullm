# Game Factory: toward 1.1 and 2.0

**Proposal, November 2026.** Build a cohesive playable chapter from a creative brief, then expand the same production system to vertical slices and complete games. This is a design roadmap; the implementation shipped today is described in [Software Factory](SOFTWARE_FACTORY.md).

The quality references are Boiling Frog Games' Oíche and Eclosion Season (the local Eclosion Garden build). Initial source inspection found useful production patterns in both; complete playthroughs still need to establish a concrete acceptance rubric. The aim is coherent art, believable spaces, connected game systems, and a story that flows through play.

## The release targets

[Dan Shapiro's maturity model](https://www.danshapiro.com/blog/2026/01/the-five-levels-from-spicy-autocomplete-to-the-software-factory/) describes Level 4 as specification and product management with autonomous implementation, and Level 5 as a factory that turns specifications into software. Use these as operating modes, with results measured for named workloads.

| Target | Human's role | Factory's deliverable |
|---|---|---|
| 1.1: Level 4 game production | Set creative direction, approve the plan, play the result, answer genuine exceptions | A cohesive chapter or vertical slice, with implementation, assets, checks, repairs, and review evidence |
| 1.1: first Level 5 workload | Approve a bounded brief and acceptance contract before starting | A small complete game or chapter in one qualified template, delivered without human code writing, code review, or intervention during the run |
| 2.0: broader Level 5 production | Specify the game and its delivery policy | Multiple connected chapters or a complete game within qualified genres, including continuity, progression, packaging, and acceptance evidence |

Start with a proposed 10–15 minute chapter: one environment, a small cast, three story beats, and two or three mechanics that reinforce one another. Include a real ending, save/load, controls, audio, and recovery from failure. Start with Three.js and one template: both local reference projects already use it. Keep engine-specific import, replay, and packaging behind adapters so native engine support can use the same contracts later.

A run that needs a human can still produce a good game. Record it as assisted, rather than counting it as an unattended success. Human playtesting between briefs improves the next contract; mandatory human approval inside a run belongs to the Level 4 mode.

## Build on the existing Factory

The current system already provides isolated worktrees, task dependencies, bounded repair, executable gates, artifacts, optional choices, required human decisions, and several visual views. Independent projects can run together. The CSV-to-JSON starter demonstrates a small unattended delivery; Peg Bloom provides a game case study with inspectable evidence.

The largest additions are a shared game/asset model, reproducible gameplay, selective audiovisual evidence, durable worker recovery, and production templates. A dead worker is not currently reconstructed just because the web server restarts.

Meshy operations already exist in [router/meshy.py](../router/meshy.py), and Tripo and Rodin submission adapters exist in [router/world_providers.py](../router/world_providers.py). These are starting points, not a verified end-to-end game asset pipeline. The requested provider is Tripo, distinct from the existing TopologyAI catalog entry. Hitem3D, Polyfork, Blender, and TRELLIS integration are proposed work.

## Patterns already present in the reference games

Initial read-only inspection found these concrete foundations:

- **Eclosion:** a simulation solver and shipping-seed witness, replay hooks, milestone screenshots, region-specific palette probes, fixed-camera scenery galleries, and distinct structural versus GPU performance checks. Its scenery harness records a useful failure case: logic tests can pass while every biome still looks like the same neighborhood.
- **Oíche:** separate game, engine, and siege systems; Polyfork loading helpers; sector-based mesh instancing and culling; bot fight/campaign tools; and real-input smoke tests that inspect audio activation, menus, movement, attacks, and pause/resume.

Generalize these into reusable template capabilities: an observable game-state interface, input replay, semantic milestones, named camera views, asset provenance, and performance probes. Inspecting a test's source does not establish that the current build passes it. Preserve the distinction between source inspection, a captured scene, and a completed playthrough.

## One contract for story, systems, and assets

The project contract should contain a short creative brief and structured production data:

- **Creative direction:** player experience, visual references, palette, architecture, lighting, scale, character silhouettes, sound, and explicit exclusions.
- **Story and play:** beat graph, player goals, required interactions, world-state changes, dialogue conditions, failure/retry rules, and chapter transitions.
- **Technical limits:** target platforms, input methods, accessibility settings, frame-time and memory budgets, save compatibility, permitted asset sources, and spend limits.
- **Acceptance:** executable invariants, named replay scenarios, representative views, audiovisual criteria, and delivery format.

Represent their relationships in one dependency graph: a story beat depends on a mechanic, the mechanic on scene objects and state, those objects on meshes/materials/rigs/animations/audio, and each relationship on checks and evidence. Stable IDs let a changed door animation invalidate the doorway interaction replay and its clip without rebuilding unrelated dialogue.

Cohesion becomes inspectable. A prop has a place in the world and a consistent material treatment. A story beat has a playable consequence. A character's rig, interaction sockets, animation transitions, collision, and dialogue refer to the same character identity. Cross-chapter state has explicit migration and continuity checks.

Templates should contain tested systems with extension points: traversal, camera, interactions, dialogue, inventory, objectives, save/load, menus, audio mixing, and packaging. Generate the chapter's content and variations around those systems. Version templates and test upgrades against existing games.

## Asset production and model routing

Use a common asset-job interface for Meshy, Rodin, Tripo, [Hitem3D](https://docs.hi3d.ai/en/api/api-reference/list/create-task), and local generators such as [Microsoft TRELLIS.2](https://github.com/microsoft/TRELLIS.2). Record provider/model revision, source references, job ID, cost, license, and output hashes. Qualification must cover submission, polling, downloading, import, and failure recovery. A provider being configured is not evidence that its output works in the game.

Use [MCP for Blender](https://github.com/ahujasid/mcp-for-blender) for agent-directed inspection and authoring. Its documented tools include scene inspection, visual inspection, Python execution, and asset generation/import. Save the resulting Blender scripts and source files so normalization and exports can be replayed in controlled build jobs.

Every accepted asset needs a manifest: units, pivot, bounding box, mesh budget, UVs, texture maps and color spaces, material slots, collision, LODs, skeleton, animation clips, root motion, and interaction sockets where applicable. Validate imports in the target engine. Check deformation and transitions in motion, and materials under the chapter's actual lighting. A good standalone render is only one piece of evidence.

Routing should consider capability, measured success rate, latency, privacy, GPU availability, and total cost. Reuse validated assets and templates first. Use deterministic tools for conversion and checks, local models for suitable generation/repair, vision models for visual diagnosis, and stronger remote models when the task and budget justify escalation. Asset credits and retries count toward the same project budget as inference. Never silently switch provider or model in a way that breaks style consistency or reproducibility.

## Polyfork as a curated asset source

Start with a searchable Polyfork picker and an agent-facing search/import interface. Its [agent API](https://polyfork.dev/prompt.txt) exposes dimensions, palette, triangle budgets, rig information, and themed kit contracts. Select coherent kits before generating missing assets; preserve the asset ID, parameters, source URL, hash, and license choice in the project manifest.

The [current pricing](https://polyfork.dev/pricing) makes low-poly models free and reserves HD editions for paid plans. The [licensing terms](https://polyfork.dev/licensing) explicitly allow products to search and load free models directly from Polyfork's CDN. Fetch on demand, identify muLLM, respect rate limits, and name Polyfork in the picker. Free mesh files also offer CC BY 4.0 with attribution; source modules and HD files have different redistribution terms. Plan offline exports around the selected license. Do not turn its restricted source/catalog into a competing commercial asset generator. Hosting restricted assets for Factory users requires appropriate platform rights.

A contextual “View HD options at Polyfork” link can be useful when an HD edition exists and fits the project's performance budget. No public affiliate program was found in the reviewed pages or search. Treat commissions as an unconfirmed partnership opportunity; disclose any future affiliate link and keep asset ranking based on project fit. An ordinary integration is worthwhile independently of referral revenue.

## Evidence selected by change impact

The evidence planner chooses the smallest adequate set of checks from the dependency graph and the acceptance contract. It records why each check ran or was reused. Unknown impact, shared-system changes, and weak coverage broaden the selection.

| Changed area | Fast feedback | Evidence when needed |
|---|---|---|
| Isolated logic or data | Relevant unit/state checks and affected replay | Event log; screenshots only if presentation changes |
| Mesh, texture, lighting, or layout | Asset validation, affected scene views, collision/navigation checks | Before/after contact sheet at fixed cameras, including in-game context |
| Rig, animation, movement, camera, or interaction | Affected deterministic gameplay replay | Short clips covering transitions and timing, with event markers |
| Dialogue, music, sound, or synchronization | State checks, subtitle/layout checks, audio checks | Gameplay clip with real game audio and synchronized captions/events |
| Chapter completion or shared engine change | Full chapter acceptance and relevant regression scenarios | Complete playthrough with sound, save/reload evidence, performance report |
| Release candidate | Required platform suite, installation, representative seeds and full-game continuity | Indexed review bundle, playable build, retained failures and delivery manifest |

Selection and retention are different. Playwright's [`retain-on-failure`](https://playwright.dev/docs/videos) still records the successful test before discarding its video. To save encoding time, decide whether to record before the run. Browser screenshots, traces, and video are useful for web games; full gameplay audio requires an explicit capture path and synchronization checks. A video file alone must not satisfy an audio requirement.

Use cheap event logs and fixed-seed replays throughout. Add sparse screenshots for visual checkpoints; short clips around changed behavior; full audiovisual captures at chapter milestones and release. A bounded rolling capture buffer can preserve the lead-up to intermittent failures where its measured overhead is worthwhile. If replay cannot reproduce a failure, retain the original observations and flag the gap.

Cache evidence against content and dependency hashes, engine/tool versions, capture settings, seed, platform, and relevant environment. Label reused evidence with its original build and covered dependencies. Never present an old screenshot as a fresh capture. Test performance separately from expensive capture, since encoding can change the frame time being measured.

Keep a mandatory minimum suite and periodic full runs. Validate the selector with known regressions and sampled checks it would otherwise skip; track missed defects as well as seconds saved. AI can propose dependencies and diagnose failures, but executable checks and measured coverage determine acceptance. Visual critics provide useful findings; agreement between models alone does not establish that gameplay is fun.

Measure **time to an accepted playable result**, GPU/CPU seconds, inference and asset spend, capture/encoding cost, storage, reviewer time, and escaped regressions. Optimize the critical path while preserving the required evidence. Compare equivalent workloads before claiming savings.

## A workspace for people and agents

Keep forest, orbital, city, and plain views as presentations of the same live project graph. Zoom from several projects into one chapter, then a task, attempt, or asset. Each project should open directly to its playable candidate, latest evidence, changed story beats, current cost, and the next decision.

A review panel should pair before/after frames with a timeline, short clips with sound, and links from a visible defect to its asset, task, replay, and repair. Completed projects stay visible with their last accepted build. Progress and estimates come from execution records.

Keep three decision states explicit:

- **Running or completed:** no action needed.
- **Optional A/B/C:** visible default and deadline; continue with the preauthorized default if unanswered.
- **Need Human:** blocked until a real decision arrives; no timeout approval.

Agents use the same API objects and decision IDs as the UI. Add a durable notification outbox with delivery status and retries. Extend adapters for Slack, Teams, email, SMS, Signal, WhatsApp, PagerDuty/APM, webhooks, and 0101 push as each transport is qualified. Keep decision state in muLLM even when a transport is unavailable. Notification previews should link to the evidence and explain the consequence of each choice.

## Implementation order and exit checks

1. **One playable template and contract.** Produce a complete chapter with a story/mechanic graph, stable asset IDs, a style guide, and independently defined acceptance scenarios. Demonstrate save/reload and an ending.
2. **One reliable asset pipeline.** Qualify one generator plus Blender normalization and engine import. Exercise retry, malformed assets, rig/animation validation, and attribution. Add providers behind the same manifest afterward.
3. **Replay and audiovisual evidence.** Capture fixed scenarios, before/after views, and gameplay with sound. Link every artifact to a candidate and scenario; automatically detect missing tracks and capture failures.
4. **Selective checks and capture.** Implement conservative dependency invalidation, evidence caching, and cost accounting. Demonstrate that known seeded regressions are still caught while redundant work decreases.
5. **Durable execution and decisions.** Resume interrupted workers from checkpoints; reconcile provider job IDs before retrying paid submissions; reserve budgets and GPU capacity. Verify crash/restart without duplicate charges or lost human decisions.
6. **Qualify autonomy, then scale.** Run a published set of varied briefs and seeds with no human edits or code review. Report accepted, failed, assisted, and abandoned runs, quality criteria, costs, and intervention counts. Expand to linked chapters once continuity survives the same process.

The first implementation should deliver one chapter all the way through this loop. That gives 1.1 a useful Level 4 product and a concrete path to a small Level 5 workload, while 2.0 grows the breadth of games it can reliably deliver.

## Keep evidence useful without bloating Git

Commit contracts, replay definitions, acceptance checks, manifests, and a few representative images. Store large videos, repeated captures, generated build archives, and transient logs in artifact storage with hashes and retention rules. Keep accepted milestone evidence and failure exemplars long enough to reproduce and review results; mark expired artifacts clearly. The repository should explain and reproduce the result without carrying every iteration's media.
