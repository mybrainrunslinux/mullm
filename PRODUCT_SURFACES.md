# Product Surfaces To Preserve

The refactor should keep the core product smaller than the old tree, but these
features are real user-facing value and should not be lost.

## Core

- Local-first cost-aware routing.
- Groundtruth/deterministic tier.
- Semantic cache and cost logs.
- Big stop / runaway spend controls.
- Local-only mode.
- Privacy-preserving analytics and content-obfuscation options.
- OpenAI-compatible endpoint for coding tools.

## Power Modes

- `normal`: route to the cheapest tier expected to satisfy quality.
- `local_only`: never call cloud providers.
- `with_rice`: deliberately not cost-optimal; run premium models in parallel
  such as GPT-5.x, Claude Opus, and Gemini Pro/Preview, then merge answers.

`with_rice` should be budget-gated and visually distinct because it is a
quality/power boost, not a savings path.

## Research

The research endpoint is a keeper:

- Break one sentence into multiple research questions.
- Classify and route subquestions in parallel.
- Preserve citations.
- Export clean citation formats such as APA and BibTeX.
- Produce PDF reports.

This belongs in `mullm-core` or `mullm-research`, not in the game/studio module.

## Research Lab / Review UI

muLLM should keep the pattern of doing advanced evaluation and human review
inside the app, not only through terminal scripts. These are additive research
surfaces and belong under the `research` group in the page registry:

- classifier holdout verification and annotated human-review queues,
- benchmark dashboards and MegaBench result browsers,
- 2D/3D routing and classifier visualizations,
- best-of-N sampling review and comparison tools,
- ONNX task generation, validation, save/review workflows,
- PR-Gauntlet and muPatch result review, including visual before/after checks,
- side-by-side and 3D comparison pages for provider/model outputs.

Current pages to preserve include:

- `/research`
- `/review`
- `/bench`
- `/megabench`
- `/onnx`
- `/compare`
- `/compare3d`
- `/dataviz`
- `/pareto`
- `/minitest`
- `/accuracy`
- `/competitive`

Some of these pages are restored as HTML before their FastAPI endpoints are
fully restored. That is acceptable during the refactor, but they should be
tracked as degraded rather than deleted. If an endpoint is missing, the page
should show a clear local-only/degraded state and the implementation should be
restored behind the same URL when possible.

## Knowledge Connectors

Joplin and Obsidian should be separate connectors:

- Joplin: human-facing notes, clipping, attachments, and selected chat exports
  through the local Web Clipper API.
- Obsidian: local Markdown vaults as AI working memory. Index `.md` files into
  ChromaDB with file path, headings, tags, and frontmatter metadata. Keep the
  source files in the user's vault; muLLM stores embeddings/chunks only.

Obsidian sync should be opt-in, local-only by default, and safe to run repeatedly:

- scan changed files by mtime/hash,
- chunk by heading/paragraph,
- embed locally when possible,
- store provenance for every answer,
- never mutate vault files unless the user explicitly asks for note creation.

## Studio

Studio should be pluggable:

- 3D studio and rigging.
- Video studio.
- Texture generation.
- Sound recorder.
- Musaic / instrument studio.
- APK/iOS packaging helpers.

These are good demos and real workflows, but they should not define the core
scientific claim.
