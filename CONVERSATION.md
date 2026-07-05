I have written a paper for submission to EMNLP 2026 and the submission deadline is coming up. There is a piece of software that needs to also have some steps completed, but it is software I've been using for months now. 

That said, I still have some steps to complete and need a real plan to try to get this all done in the next 15 days (actual days):

DUNS number for 0101 Technology LLC (new-ish but already established company)
Email account(s) for 0101 Technology LLC (possibly Google Workspace, trying to avoid the cost but also not going to be happy with 5GB limits or lack of deliverability)
Possibly autoresponder that also handles the form submissions for me from the site
Getting the site online
This sounds impossible but the site is 95% done, the hosting is there, I just need to add a vhost in nginx and allow US traffic in the firewall. Legal terms docs are all written (privacy policy, footer, GDPR/CCPA disclosures)
Getting a site online for mullm itself
Validating the new install / packaging process on several OS
Signing and publishing mullm to PyPI or some other platform
Signing up for actual conference submission
This involves something called Overleaf to check the page count too?
Possibly also sign up for ORCID researcher ID?
Also sign up as reviewer and be ready to review other submissions without AI help.
Submit the paper for consideration with a fully completed submission form.
Determine when it is best / ethical to upload the actual software. On one hand, it is good to hold for anonymous review. On the other, this software solves REAL PAIN that people are having daily, now. Holding it for even a month or two is detrimental to the actual world.
Build a monetization strategy and pipeline either based on pure SaaS arbitrage strategy, premium feature strategy, some other monetization (ads?) or combination.
Prepare the actual slides in A4 and an A0 poster for the conference, be ready if we are accepted. Have a pivot plan if not.
Build more software and show off the software.
Write about software.
Show less
8:30 PM
Claude responded: Let me grab a few facts before I draft this — EMNLP 2026 dates, the ARR/anonymity policy for code, and the current DUNS process all gate the plan.

Weighing anonymity ethics against urgent software release timing
Weighing anonymity ethics against urgent software release timing
Let me grab a few facts before I draft this — EMNLP 2026 dates, the ARR/anonymity policy for code, and the current DUNS process all gate the plan.


Clarifying anonymity policies and public release timing ethics
Clarifying anonymity policies and public release timing ethics
Good - May 25 is exactly 15 days from today. Now the anonymity question for software release timing:


Reassessing whether DUNS number is actually necessary
Reassessing whether DUNS number is actually necessary
DUNS process current state:


Architected comprehensive 15-day submission plan prioritizing critical dependencies
Architected comprehensive 15-day submission plan prioritizing critical dependencies
Three things changed how I'd build this plan once I confirmed them:

The deadline is exactly 15 days out. ARR May cycle submission is May 25, 2026 (23:59 AoE), then reviewer registration for all authors closes May 27. That's the hard wall.

The anonymity question has a clean answer. Since Feb 2024, ARR has no anonymity period — submissions remain anonymous during peer review, but authors are free to post and discuss non-anonymous preprints at any time. So mullm can go fully public under your name on PyPI and at mullm.com while the paper is under review. The PDF and any supplementary archive must still be anonymized (no author names, no self-revealing self-cites, anonymized repo links in the paper). One caveat: authors are reminded that widely sharing the work will make it harder to recruit reviewers, and ARR gives borderline-decision priority and certain awards to unpublicized submissions. So a quiet PyPI release + minimal landing page is fine; a Hacker News / Twitter launch campaign before May 25 trades reviewer goodwill and a borderline-decision tiebreaker for early users. I'd hold the loud launch until after July 30 meta-reviews. 
ACL Rolling Review
ACL Rolling Review

DUNS does not block anything in the next 15 days. Free DUNS is up to 30 business days; expedited processing is $229 for delivery within eight business days. File it on day 1 and forget about it — it's not on the critical path for the paper, the site, or PyPI. 
NerdWallet

Critical path (the only thing that can't slip)
By May 25 AoE, you need: a fully anonymized PDF compiled in the ARR LaTeX template (this is the Overleaf bit — the ACL/ARR Overleaf template enforces the page limit), submitted via OpenReview with EMNLP 2026 selected as the binding venue, optionally with anonymized supplementary .zip. By May 27 AoE, every author (you and your partner if they're a co-author) has to complete the reviewer registration form or the paper is desk-rejected.

Everything else on your list is parallel work that doesn't gate submission. Treat it that way ruthlessly.

Day-by-day
Days 1–2 (May 10–11, this weekend). Fire the slow async tasks first. (a) File the expedited DUNS — $229, you'll have it by ~May 21. (b) Create your ORCID at orcid.org — 5 minutes, free, you'll want it for the OpenReview profile anyway. (c) Create your OpenReview profile, attach ORCID, fill in the publication history honestly so the reviewer-matcher has signal. (d) Set up the email. My recommendation: skip Google Workspace and use Migadu ($19/year flat, unlimited domains, ~10GB) or Fastmail ($5/month, 30GB, best deliverability for the price). Both have far better reputation than self-hosted in 2026 and neither has Google's 5GB problem. Point MX records, set SPF/DKIM/DMARC properly, send a few test emails through mail-tester.com to verify a 10/10 score before anything important goes out. (e) Get the marketing site live: nginx vhost, firewall rule for US traffic, SSL via Let's Encrypt. You said this was a couple of hours — do it now while you have momentum.

Days 3–5 (May 12–14). Paper work. Pull the ACL/ARR style files into Overleaf, paste your manuscript into the template, verify it compiles at exactly 8 pages of content (long) or 4 pages (short), references unlimited, appendices unlimited. Strip every author-revealing thing: names, affiliations, acknowledgments section (gets re-added at camera-ready), "we previously showed" patterns, and any GitHub/website links that resolve to your identity. If you cite the muLLM repo in the paper, use an anonymous GitHub mirror (anonymous.4open.science is the standard tool). Read the ACL Responsible NLP Research checklist now, not on May 24 — it's mandatory at submission and asks specific questions about compute, data, and reproducibility you'll want to write up carefully. This is also where to add the "we will release the software upon publication" language.

Days 6–8 (May 15–17). Software hardening for the PyPI release. Validate the install on a clean Ubuntu 24.04 VM, a clean macOS 14+, and Windows 11 with WSL2 — these are the three that matter. Set up a GitHub Actions workflow with PyPI Trusted Publishers (OIDC, no API tokens to leak) so publishing is git tag v0.1.0 && git push --tags and the action signs with Sigstore automatically. Reserve mullm on PyPI now if you haven't — namespace squatters do exist. Don't publish yet; just have the pipeline green and a release candidate sitting in TestPyPI.

Days 9–11 (May 18–20). mullm.com landing page (quiet, no launch announcement), pointing to the (still-private) GitHub and PyPI namespace. Wire up the form handler — given your stack, Formspree or a 50-line FastAPI endpoint on your existing server is faster than building autoresponder infrastructure. For autoresponse, a SES or Resend transactional integration is two hours of work; Mailgun's free tier dies fast so I'd skip it. Run the paper through a final read-through, fix the inevitable "wait, that's not anonymous" issues, regenerate the supplementary .zip with anonymized code.

Days 12–13 (May 21–22). Submission rehearsal: upload to OpenReview as a draft, verify the PDF renders, verify the supplementary archive opens, verify the venue selection says EMNLP 2026 (binding — ARR 2026 May submissions that do not select EMNLP 2026 during submission will not be able to commit to EMNLP 2026). Make sure both authors are listed if applicable and your business partner has their own OpenReview + ORCID. Check the preprint setting — for your situation I'd opt out of the "binding non-preprint" option since you want flexibility to release the software publicly under your name. 
Callforpaper

Day 14 (May 23). Submit. Don't wait until the 25th; the OpenReview submission system always melts down in the final 12 hours of an ARR cycle and you do not want to be debugging upload errors at 11pm AoE.

Day 15 (May 24). Complete reviewer registration for all listed authors (deadline May 27 but do not push it). Indicate areas of expertise honestly and declare conflicts — you'll be asked to review ~3 papers between roughly late June and July 6. No AI assistance allowed on reviews; budget 2-3 hours per paper when those land.

Items I'd defer past May 25 with intent
Conference slides (A4) and the A0 poster. Acceptance notification isn't until well after meta-reviews on July 30. Building these now is wasted motion. Sketch the narrative arc on paper, no more.
Pivot plan if rejected. Worth one hour of thinking, not a week of building. The good pivot is: rework with reviewer feedback, resubmit to ARR June cycle (which feeds AACL 2026 in Hengqin and other 2027 conferences). Rejection at ARR is much less catastrophic than at a non-rolling venue.
Monetization strategy. Don't decide this in the next two weeks. Get the free tier out, watch what people actually do with it for 30-60 days, then decide between SaaS arbitrage (you absorb the cloud-tier costs and charge a margin), premium features (semantic cache analytics dashboard, multi-user, enterprise SSO), or usage-based credits. Ads are wrong for developer tooling — don't.
Loud launch (HN, Twitter, blog posts). Hold until after July 30 meta-reviews. Quiet PyPI publish + the mullm.com landing page is fine in the interim.
"Build more software and show off the software." Post-submission, not before. May 26 onward is the time.
One thing I'd nudge you on
Your habit is surgical updates, and the paper is going to want exactly that discipline applied to the manuscript: don't rewrite sections you've been staring at for months on May 14. Diff against your last draft, fix what's actually broken, leave the rest. The thing that loses people the submission is a structural rewrite at T-72h that introduces inconsistencies the anonymization pass then misses.

Want me to draft any specific piece — the Responsible NLP checklist answers given what I know about muLLM, the GitHub Actions Trusted Publishers workflow, an anonymization sweep checklist for the paper, or the nginx vhost + firewall config?

You said: Yes to these: the Responsible NLP checklist answers given what I know about muLLM, the GitHub Actions Trusted Publishers workflow
Yes to these:  the Responsible NLP checklist answers given what I know about muLLM, the GitHub Actions Trusted Publishers workflow

Explain step by step, I have NEVER published anything, I'm not registered for anything, this is where I'm really lost. Where do I sign up after ORCID, where do I "get" or "use" Openleaf?

The paper is anonymized and the version I wish to submit has been reviewed by two people I trust, one with a LOT of AI and LLM/ML knowledge, one with more coding/engineering knowledge. I can't believe it but I am satisfied with it, and both reviewers simply said LGTM with some specifics and basically said publish it. The ONLY thing the paper needs is adjusted to that formatting, and submission after a final final eyeballing to make sure we did not lose any meaning with anonymization. If needed, I have compacted versions for the 8-page and the 4-page options, though I believe now that the full paper could fit due to the two-column layout + unlimited Citations, Appendix, and a few others that "do not count" against the limit which helps. I really am ready to submit just need to have: a mullm.com OR a 0101technology.com email address that WORKS and I appreciate you telling me how to make really sure, but since the paper is anonymized I really only need that even for the "camera ready" so really I suppose I could use MY email (or even boilingfroggames email?) for now, then later swap on the paper to a 0101technology email? Is that workable?

In any case, if I wanted to review, read-final, and submit the paper NOW what are those steps. Starting with no account, personal gmail or Boiling Frog one with the goal of eventually being "known" at the 0101technology email instead for AI research...

Show less
8:47 PM
Claude responded: Let me check current details on the ARR template, OpenReview signup flow, and the Responsible NLP checklist so I get this right.

Synthesizing submission requirements and template specifications
Synthesizing submission requirements and template specifications
Let me check current details on the ARR template, OpenReview signup flow, and the Responsible NLP checklist so I get this right.


Orchestrated submission workflow, checklist answers, and publication infrastructure setup
Orchestrated submission workflow, checklist answers, and publication infrastructure setup
One quick check on OpenReview profile moderation timing, which is the one thing that could actually trip you up if you start in the wrong order:


Synthesized email strategy, submission workflow, and institutional domain priority
Synthesized email strategy, submission workflow, and institutional domain priority
This is the most important thing I'll tell you in this whole reply, so reading it carefully matters: there's an OpenReview profile moderation gotcha that can sink the timeline if you start in the wrong order. Profiles signed up with a public email domain (gmail.com, etc.) may spend up to 2 weeks in moderation, while profiles created without an institutional email go through a moderation process that can take up to two weeks. New profiles created with an institutional email will be activated automatically. You have 15 days. A two-week wait would land you exactly at deadline with no submission account. 
OpenReview
ECVA

Translation: do not sign up for OpenReview with your personal gmail. Use your boilingfroggames.com address — it's an established LLC's domain, which OpenReview treats as institutional, and you almost certainly auto-activate. Your scheme of "use Boiling Frog now, swap to 0101technology later" is exactly right, and OpenReview supports it natively: a profile can have many emails attached, with one marked as primary, and you can change which is primary later. At camera-ready (months from now, if accepted), you put the 0101technology.com email on the paper. None of this is awkward — it's the normal workflow.

The submit-now chain, account by account
Step 1: ORCID (15 minutes, do this first)
Go to orcid.org/register. Use your boilingfroggames email. Fill in: name, email, password, country. After verification you get a 16-digit ORCID iD (looks like 0000-0000-0000-0000). On your ORCID dashboard, add at minimum: an Employment entry for 0101 Technology LLC (or Boiling Frog Games — whichever you can substantiate), and any prior Education. Set visibility to "everyone" for these. Copy your ORCID iD somewhere accessible — you'll paste it into OpenReview next.

ORCID is never moderated, never gated, free forever. This is the easy one.

Step 2: OpenReview profile (30 minutes; this is the rate-limited step, do this on day 1)
Go to openreview.net and click Sign Up. Use your boilingfroggames.com email, not gmail. If it warns you about the domain, proceed anyway — boilingfroggames is a real business and should clear quickly.

After email confirmation, you'll land on the Profile Registration page. Fill in everything you can — sparse profiles get moderated longer:

Names: First/Last as you want them to appear on publications
Emails: Add your gmail and any other emails too. OpenReview wants this for deduplication, and adding personal email here actually helps moderation (it shows you're a real person)
Personal Links: ORCID iD (paste it in), GitHub profile URL, and a homepage. A valid homepage is a website that shows your name, affiliation, and email that you used to register — your soon-to-be-live mullm.com or 0101technology.com page works, or your GitHub profile does 
OpenReview
Education and Career History: Add at least one institution. If you're independent, you can type "Independent Researcher" as the role, but if that's your only entry your profile will be rejected — add 0101 Technology LLC as current employment, and any prior education or roles going back ~5 years 
OpenReview
Expertise: List your subareas — "Efficient Methods for NLP", "Resources and Evaluation", "NLP Applications", "Interpretability and Analysis" are likely matches for muLLM. This drives reviewer-matching, so be honest and specific.
Relations: Skip if none
Submit. You'll get either immediate activation (likely, with boilingfroggames email) or a "pending moderation" email. If it goes to moderation, the homepage and ORCID greatly speed things up; if a week passes with no movement, email profile@openreview.net with your ORCID and a short explanation that you're submitting to ARR May 2026.

Your business partner needs to do this same dance if they're a co-author. Don't forget them.

Step 3: Overleaf account (5 minutes)
Go to overleaf.com, sign up with whatever email you like (doesn't matter, Overleaf has no moderation). Free tier is fine for a single paper — compile time limits won't bite you for a normal-sized ACL submission.

Step 4: ACL template (10 minutes)
The official ACL template lives at overleaf.com/latex/templates/association-for-computational-linguistics-acl-conference/jvxskxpnznfj (or search "ACL" in Overleaf's template gallery). Click "Open as Template" — this copies it into your account as your own project. Rename it to something like "muLLM ARR May 2026".

The critical first line:

latex
\usepackage[review]{acl}
The [review] option is what makes the PDF anonymous (no author block, line numbers added for reviewers). For camera-ready you'd switch to \usepackage{acl}. Verify this option is set to review before submission.

Step 5: Drop your paper into the template (1–4 hours depending on conversion)
Replace the example content with your manuscript. Specific things to verify:

Author block stays as the anonymous placeholder. The template handles this when [review] is on, but visually confirm the compiled PDF says "Anonymous ARR submission" at the top, not your name.
Limitations section is required and goes after Conclusion, before References. Extra space is allowed after the 8th page for a limitations section and an ethics/broader impact statement — these do not count against the page limit. So an 8-page paper + Limitations + (optional) Ethics + unlimited references + unlimited appendices is the maximum at submission. 
ACL 2023
Bibliography: Use BibTeX, ideally with the ACL Anthology .bib (the template ships with anthology.bib). Tools like ACL Anthology's "Export to BibTeX" button give you clean entries — don't hand-roll them.
No author-revealing self-cites: \citet{previous-our-work} is fine, but no "We previously showed (Smith, 2024)" patterns. If you cite your own prior work, treat it like third-party work in the prose.
No revealing URLs: GitHub, personal site, project domain. If you need to reference the muLLM codebase in the paper, use anonymous.4open.science — paste your GitHub URL, get back an anonymized mirror URL good for the review cycle.
Compile (the green button). Check the PDF: should be 2-column, page numbers visible, anonymous header, your content. Verify page count is ≤8 for long or ≤4 for short (excluding Limitations/Ethics/Refs/Appendices).

Step 6: ARR May 2026 submission portal
The OpenReview submission link for the ARR May cycle goes live at the cycle opening (it may already be live now). The path:

Log into OpenReview with your now-active profile
Go to the ACL Rolling Review group page: openreview.net/group?id=aclweb.org/ACL/ARR
Find the 2026 May cycle and click "New Submission"
The form will ask for:
Title and abstract (the abstract is plain text, no LaTeX commands — strip $...$ math and \cite{} to be safe)
Authors: Add yourself by ORCID/email. Add your business partner if co-author. Authors are visible to chairs, blind to reviewers — this is fine.
PDF upload: Your compiled .pdf from Overleaf
Track: pick "Efficient Methods for NLP" or "NLP Applications" or whichever fits muLLM best (the call lists tracks; pick by best fit)
Subject Areas / Keywords: pick from the menu
Preferred venue: select EMNLP 2026 — this is binding for this cycle
Preprint policy: pick the non-binding option (preserves your right to release software/preprints with your name during review)
Responsible NLP checklist: answers in the next section of this reply
Ethics statement: usually optional unless your work has clear ethics dimensions
Submission number / resubmission: skip, this is fresh
Hit Submit. Then re-open it and verify every field is what you intended. The PDF is the easiest to mess up; download it from the submission page and open it to confirm it's the right file.
Step 7: Reviewer registration (by May 27 EoD AoE)
Separate form, linked from the ARR site. You commit to reviewing 1–3 papers in late June/early July. You'll be asked for your expertise areas, language preferences, and conflicts of interest (institutions, people you've co-authored with). No AI assistance allowed for reviews. Budget ~2–3 hours per assigned paper when they land.

Responsible NLP Research Checklist — draft answers for muLLM
This goes in the OpenReview submission form, not as a separate PDF (changed in 2024). For each "Yes" answer, point to a section in your paper. Tailor my drafts to match what's actually in your manuscript:

A1. Limitations — Yes, Section Limitations. (You have this section already since it's mandatory.)

A2. Risks — Yes, Section Limitations or Ethical Considerations. For muLLM, plausible risks to discuss in 2–4 sentences: (a) routing decisions that escalate to cloud tiers may leak sensitive prompts to third-party providers; users should be aware of which tier handles their data; (b) lowering inference costs may increase aggregate compute usage (Jevons paradox), partially offsetting per-query efficiency gains; (c) cache poisoning is a security consideration for shared deployments. If you don't already have a paragraph like this, add one — it's cheap and reviewers look for it.

B. Did you use or create scientific artifacts — Yes (muLLM is the new artifact; you also use Qwen, llava, ChromaDB, Ollama, FastAPI, Whisper).

B1. Cite creators — Yes, Section Implementation (or wherever you describe the stack). Cite: Qwen technical report, LLaVA paper, Whisper paper (Radford et al.), ChromaDB (URL/repo if no paper), Ollama (URL). State version numbers where they matter.
B2. License/terms — Yes, Section Implementation or Released Artifacts. State Qwen license (Tongyi Qianwen License — check the specific Qwen3.5 variant's license), Whisper (MIT), ChromaDB (Apache 2.0), Ollama (MIT), FastAPI (MIT). State muLLM's planned license (MIT, per your earlier plan).
B3. Intended use — Yes, same section. State that you use the upstream models for the inference purposes their licenses permit, and that muLLM is released as a research/production tool consistent with each component's license.
B4. PII / offensive content — N/A, with justification: "muLLM is a routing layer; it does not collect or train on user data. The system processes queries at inference time without persistence beyond the optional local semantic cache, which the operator controls." (If your eval used any benchmark with PII concerns, address that here instead.)
B5. Documentation — Yes, Section Implementation and/or Appendix. Note the languages your eval covers (English-only? multilingual?), the domains tested (chat, code, etc.), and that a model/system card will accompany the release.
B6. Statistics about data — Yes, Section Evaluation (or wherever your numbers are). Make sure you report: number of queries in your eval set, train/val/test split if applicable (probably N/A for muLLM since you're evaluating routing, not training), and per-tier counts (how many queries hit cache vs. local vs. cloud).
C. Did you run computational experiments — Yes (cache hit rate measurements, escalation rates, latency, cost comparisons).

C1. Parameters, compute budget, infrastructure — Yes, Section Experimental Setup and/or Appendix. State: Qwen3.5 9B (~9B params), llava:13b (~13B params), local host (RTX 5090 24GB VRAM, 32-core CPU, 192GB RAM — anonymized as "a single workstation with consumer GPU"), and the cloud APIs used for upper tiers. Estimate total experiment wall-clock time.
C2. Hyperparameter search, best-found values — Yes, Section Experimental Setup or Appendix. Report the cache similarity threshold, escalation triggers, and how you arrived at them (manual tuning, grid search, etc.).
C3. Descriptive statistics — Yes if you ran multiple seeds/repeats; if single-run, state that explicitly. Don't claim error bars you didn't compute.
C4. Existing packages — Yes, Section Implementation. Versions for ChromaDB, Ollama, FastAPI, Whisper.
D. Did you use human annotators / research with human participants — No, N/A. Justification: "This work does not involve human subjects. Evaluation is conducted on programmatically generated and curated query sets without human annotation." (If you did any user study or human eval, switch to Yes and answer D1–D5.)

E. Did you use AI assistants in research, coding, or writing — Yes.

E1. Be honest here. Example wording: "AI assistants (Claude, GitHub Copilot) were used during software development for code completion, debugging, and documentation drafting. AI writing assistance was used for grammar and clarity revisions on the manuscript. All technical claims, experimental design, results, and conclusions are the authors' own. No AI system is credited as an author." This matches the ACL policy expectation. Reviewers won't penalize honest disclosure; they will penalize concealment if it's discovered.

GitHub Actions Trusted Publishers — workflow for PyPI
This is post-submission work (days 9–11 in the original plan), but here's the complete recipe so you have it. Trusted Publishers means PyPI accepts uploads from your specific GitHub Actions workflow via OIDC, with zero long-lived API tokens. Sigstore signatures are attached automatically.

One-time setup on PyPI
Create accounts on pypi.org and test.pypi.org (separate accounts, same email is fine). Enable 2FA on both.
On pypi.org → your account → Publishing → Add a new pending publisher. Fill in:
PyPI Project Name: mullm
Owner: your GitHub username or org
Repository name: mullm (or whatever the repo is)
Workflow name: release.yml
Environment name: pypi
Repeat on test.pypi.org with environment name testpypi.
A "pending publisher" reserves the name and trusts the workflow before the first release. After your first publish, it converts to a regular Trusted Publisher.

One-time setup on GitHub
In your repo → Settings → Environments → create two environments: pypi and testpypi. On the pypi environment, add a protection rule requiring manual approval (this gives you a "are you sure?" gate on real releases). On testpypi, no protection needed.

Workflow file
Put this at .github/workflows/release.yml:

yaml
name: Release to PyPI

on:
  push:
    tags:
      - 'v*'

permissions:
  contents: read

jobs:
  build:
    name: Build distribution
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install build tooling
        run: python -m pip install --upgrade build
      - name: Build sdist and wheel
        run: python -m build
      - name: Upload distributions
        uses: actions/upload-artifact@v4
        with:
          name: dist
          path: dist/

  publish-testpypi:
    name: Publish to TestPyPI
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: testpypi
      url: https://test.pypi.org/p/mullm
    permissions:
      id-token: write   # Required for Trusted Publishing (OIDC)
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          repository-url: https://test.pypi.org/legacy/

  publish-pypi:
    name: Publish to PyPI
    needs: publish-testpypi
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/p/mullm
    permissions:
      id-token: write
      contents: write   # Needed to create a GitHub Release
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: dist
          path: dist/
      - uses: pypa/gh-action-pypi-publish@release/v1
        # Sigstore signatures are attached automatically by this action
      - name: Create GitHub Release
        uses: softprops/action-gh-release@v2
        with:
          files: dist/*
          generate_release_notes: true
How releases work after setup
bash
# In your repo with everything committed
git tag v0.1.0
git push --tags
That's it. The workflow:

Builds sdist + wheel
Uploads to TestPyPI (auto, no approval needed)
Pauses on the pypi environment, waits for your manual approval in the Actions UI
On approval, uploads to PyPI with Sigstore signatures and creates a GitHub Release
The id-token: write permission and the absence of any PYPI_API_TOKEN secret are the heart of Trusted Publishers — there's no credential to leak.

pyproject.toml minimum
toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mullm"
version = "0.1.0"
description = "Tiered LLM routing pipeline with semantic cache, local inference, and cloud escalation"
readme = "README.md"
requires-python = ">=3.10"
license = "MIT"
authors = [{ name = "Your Name", email = "you@0101technology.com" }]
keywords = ["llm", "routing", "inference", "cache", "ollama"]
classifiers = [
  "Development Status :: 4 - Beta",
  "License :: OSI Approved :: MIT License",
  "Programming Language :: Python :: 3",
  "Topic :: Scientific/Engineering :: Artificial Intelligence",
]
dependencies = [
  # your runtime deps
]

[project.urls]
Homepage = "https://mullm.com"
Repository = "https://github.com/YOUR_USERNAME/mullm"
Issues = "https://github.com/YOUR_USERNAME/mullm/issues"

[project.scripts]
mega = "mullm.cli:main"  # matches your existing `mega` CLI
Hatchling is a sensible default for new projects; if you have an existing setup.py you prefer, that works too — Trusted Publishers is build-backend-agnostic.

Order of operations starting right now
Today: ORCID, then OpenReview signup (boilingfroggames email), then Overleaf signup + template duplicated.

Tomorrow through ~day 5: paper into template, compile, eyeball anonymization, check page count.

Day 6 onward: submit (don't wait for day 14), then reviewer registration, then everything else from the original plan.

The single most failure-prone step is OpenReview moderation, which is why everything before it is "today." If your boilingfroggames profile activates immediately, you have headroom. If it goes into moderation, you have time to email support and recover. If you signed up with gmail on day 10, you would have no recovery path.

Want me to draft the actual Limitations and Ethical Considerations paragraphs for the paper once you've checked over the checklist answers, or look at the anonymization once you have a compiled PDF you can paste in?

You said: ok I still have questions, and I am strongly leaning toward publishing the full 0101 website, by next weekend, trying to have the ORCID and OpenReview stuff al…
ok I still have questions, and I am strongly leaning toward publishing the full 0101 website, by next weekend, trying to have the ORCID and OpenReview stuff also by then, and perhaps skipping the conference, maybe even the paper as a whole, releasing muLLM as either Apache2.0 or community-plus-paid or building a separate muLLM Enterprise or muLLM Pro or something. 

Here's the main reason: you said "Education and Career History: Add at least one institution. If you're independent, you can type "Independent Researcher" as the role, but if that's your only entry your profile will be rejected"

... I am very light on education, not affiliated with a university, this research was done in homelab, the software was built in homelab entirely outside of work hours. 

Yes, I do have contract work, I used to work for a few bigger name companies, but does any of that qualify? It is tough to substantiate boiling frog... the company has been registered for a while but the site is locked down fully, we have a handful of testers that can possibly get to it and even fewer have access to boilingfrog.dev (developer areas/tools).

It sounds even tougher to substantiate 0101 but at least I have the option of allowing US and Canada access and possibly even Hungary or other countries to 0101technology.com, if I need to allow all-but-embargo-countries (so exclude OFAC, seems totally fine the ACL terms themselves exclude OFAC even outside of the US...) that can be done, I'll probably supplement the nginx with published-static cloudflare pages, just may need help figuring out SAFE form submission. I've even wondered if we can host it on this secured hardened nginx thing, could the form submit be really lazy... the data just goes to like a JSON or md file if it is deemed safe and another process (or me) makes sure there is a response from an actual human within a business day or so, in other words ship that md or json file on a cron schedule back to even desktop.... I know, some of this sounds super clunky and old school but in my opinion the world is coming back around to kind of ... this. it works, it is easier than dealing with heuristic analysis 7-layer edge bot detection ruleset blocking and so on, still probably need a captcha and maybe I'm missing something but figuring with very strong linux rules we can do this in a narrow scoped folder that can even only hold that filetype we can scan it, do whatever.

Along those lines... mullm itself... there's the whole mess, there's the CLI it is kind of. permissive, maybe not as much as other harnesses but it definitely has some level of risk of damage as in actually running it. I was wondering on two fronts, if it is feasible to add some kind of "sandbox" toggle to it where it can only operate within a folder where it is installed (sensible default or user specifies) then we can have like multiple git repos in there if needed but maybe it has some limits. Second, more important, I've done a lot of work on the security and privacy front on mullm, but is there a virus scan or attestation or something I can provide as in "this is not malicious" like upload it myself to virustotal or something similar (it's a python wheel at the moment) to show that it scans clean - I've already run many scans like Grype, badger, semgrep and addressed anything that came up including a few unexpected CVEs with interesting fixes. 

Clarifying: Apache2.0 not MIT for mullm, no co-author on this one. Just me.

Ok so opinion: 0101 including email then ORCID, overleaf, template, check it, adjust anonymized md paper to the ACL template including citations and ordering, OpenReview signup, submit the paper with your opinion either 0101 Technology LLC alone, or some combination of places I work now, have worked, co-founded, or the place I contract and/or the middleman contracting firm through !

Show less
9:38 PM
Claude responded: Let me push back on the most important thing first, because I think you're talking yourself out of the conference for a reason that isn't actually as solid as …

Weighed conference submission against independent release strategy comprehensively
Weighed conference submission against independent release strategy comprehensively
Let me push back on the most important thing first, because I think you're talking yourself out of the conference for a reason that isn't actually as solid as you think — and then I'll answer the rest.

The "I'm not academic enough" thing is a misread
The OpenReview profile rejection rule is about empty profiles, not non-academic ones. Re-read the quote: If the "Education and Career History" section only lists "Independent Researcher" we will ask you to add another institution record. The bar is "more than one entry." You have: 
OpenReview

0101 Technology LLC (current, founder/principal — a registered legal entity)
Boiling Frog Games (current or recent — also a registered entity)
A current contracting engagement (you can list the end client OR the middleman firm — both are legitimate, and listing the middleman is often what consultants do)
"A few bigger name companies" you used to work at
That's four entries minimum. None of them need to be a university. None of them need to substantiate themselves on the public web. OpenReview doesn't crawl your domains — they look at the homepage link you provide (which can be your GitHub profile, full stop) and the totality of the profile. Tons of OpenReview accounts belong to industry researchers, indie devs, and people who left academia 10 years ago. You fit cleanly.

Education: list whatever you have, even if it's just a community college course or a bootcamp or "self-taught (autodidact)" as the institution. They want to see something, not a PhD. If you genuinely have nothing, leave it sparse and lean harder on career history. Career carries the load.

I'd seriously reconsider skipping. Here's the honest tradeoff:

Cost of submitting: ~5 days of remaining work (template + formatting + final eyeball + submission UI), plus ~6–9 hours of reviewer labor in late June, plus the borderline-decision tiebreaker if you go loud with mullm before review concludes.

Benefit of submitting: Free expert peer review on work you've already done. ACL Anthology indexing means anyone searching for "tiered LLM routing," "semantic cache + escalation," etc. finds your paper for the next decade. A real CV credential that makes the monetization conversation easier ("EMNLP 2026 paper" beats "GitHub repo" in any enterprise sales call). And critically, the ARR policy lets you do both — release mullm publicly under Apache-2.0 right now, with your name attached, while the anonymized PDF sits under review. You don't have to pick. You only give up the anonymous-submission borderline tiebreaker and the special unpublicized-paper awards, which are small.

If you skip, the realistic outcome isn't "I'll submit later" — it's "I'll never submit." Papers that don't ship on the deadline they were written for almost always rot. The work is done. Ship it.

That said: it's your call. If you decide to skip, that's a defensible choice. Just make it deliberately, not because of an imagined credential gap.

What to actually put as affiliation
For the OpenReview career history section, list all of them truthfully:

Current: 0101 Technology LLC — Founder / Principal (or whatever your actual title is). Domain 0101technology.com.
Current: Boiling Frog Games — Co-founder / [role]. Domain boilingfroggames.com. Even if the public site is locked down, the LLC is real.
Current: Whichever entity holds your contract — pick the one that's easiest to substantiate. If it's a middleman firm with a public web presence, use that. If the end client is bigger-name, use the end client. Either is legitimate.
Past: The "bigger name companies" you used to work for, with approximate date ranges. These actually help your moderation outcome more than anything else because OpenReview can verify those entities trivially.
For the paper byline at camera-ready (months from now, only if accepted), single author with single affiliation is cleanest:

[Your Name]
0101 Technology LLC
[city, country]
contact@0101technology.com

That's it. Don't list past employers on the paper; they didn't fund this work. Don't list Boiling Frog Games unless it was actually involved in the research (sounds like it wasn't — homelab, off-hours). Don't list the contracting firm unless they funded the work (sounds like no). One author, one entity, one email. Clean.

Email contact: you can use contact@, peter@, research@ — whatever you want. People expect a real human email on a paper, not noreply@.

The form submission architecture
Your instinct is correct and the approach is sound. Static site on Cloudflare Pages, dynamic POST endpoint on your hardened nginx box, files-as-queue with cron-driven email-back to desktop. This is coming back into fashion among security-aware developers and there are concrete reasons it's superior to most form-handler SaaS: no third-party data custody, no JavaScript dependency, full audit trail, trivially auditable threat model.

A few specifics so the implementation is bulletproof:

Nginx alone can't write request bodies to files without help — it doesn't have a "POST to file" handler. You need a tiny backend. Since you already run FastAPI for muLLM, use that:

python
# form_handler.py — ~40 lines
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, EmailStr, constr
import json, uuid, os, time, pathlib

QUARANTINE = pathlib.Path("/var/lib/0101/quarantine")
QUARANTINE.mkdir(parents=True, exist_ok=True)

app = FastAPI()

class Submission(BaseModel):
    name: constr(min_length=1, max_length=200)
    email: EmailStr
    subject: constr(min_length=1, max_length=200)
    message: constr(min_length=1, max_length=5000)
    turnstile_token: constr(min_length=1, max_length=2048)
    honeypot: str = ""  # must be empty

@app.post("/api/contact")
async def contact(submission: Submission, request: Request):
    if submission.honeypot:
        raise HTTPException(400, "bot detected")
    # verify_turnstile(submission.turnstile_token, request.client.host)
    payload = {
        "id": str(uuid.uuid4()),
        "ts": time.time(),
        "ip_hash": hash(request.client.host),  # privacy-friendly
        **submission.model_dump(exclude={"turnstile_token", "honeypot"}),
    }
    path = QUARANTINE / f"{payload['id']}.json"
    path.write_text(json.dumps(payload, indent=2))
    os.chmod(path, 0o440)  # immutable from app perspective
    return {"status": "received"}
Filesystem hardening for the quarantine folder:

bash
# Run once during setup
mkdir -p /var/lib/0101/quarantine
chown nobody:nobody /var/lib/0101/quarantine
chmod 0733 /var/lib/0101/quarantine  # write+execute, no read for others
# Append-only on supported filesystems (ext4):
sudo chattr +a /var/lib/0101/quarantine
# No execution from this mount: in /etc/fstab, ensure noexec,nosuid,nodev
Nginx in front, doing what it's actually good at:

nginx
# Rate limiting zone
limit_req_zone $binary_remote_addr zone=contact:10m rate=5r/m;

server {
    server_name 0101technology.com;

    # Body size cap — form submissions are tiny
    client_max_body_size 16k;
    client_body_buffer_size 16k;

    location /api/contact {
        limit_req zone=contact burst=2 nodelay;
        limit_except POST { deny all; }
        proxy_pass http://127.0.0.1:8200;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Everything else is static
    location / {
        root /var/www/0101;
        try_files $uri $uri/ =404;
    }
}
Cloudflare Turnstile (not hCaptcha or reCAPTCHA) is the right CAPTCHA here — invisible 90% of the time, privacy-friendly, free, integrates in 5 lines of JS. The token you receive in turnstile_token you POST to https://challenges.cloudflare.com/turnstile/v0/siteverify server-side to validate before accepting the submission.

Cron-driven email back to desktop: a simple script that runs every 5 minutes, looks for *.json in quarantine, validates structure, emails the contents to your inbox via the SMTP relay of whatever provider you ended up with (Migadu/Fastmail/Resend), and moves processed files to /var/lib/0101/processed/. ~30 lines of Python. AV scan in between? clamscan on the JSON before email-out is the right pattern — fast for tiny files.

For the embargoed-countries question: yes, your reading is correct, US-incorporated entities including 0101 are bound by OFAC. Easiest implementation is Cloudflare's "Country" firewall rules at the edge — block the OFAC-sanctioned list (currently Cuba, Iran, North Korea, Syria, the occupied regions of Ukraine, plus a few others — check the current OFAC list because it changes). One firewall rule covers it. You don't need to block more than OFAC requires; "allow US and Canada only" is too restrictive and hurts you outside the US.

muLLM sandbox toggle
Two layers, both worth having:

App-level sandbox (always on, ~1 hour to add):

python
# mullm/sandbox.py
import pathlib
from typing import Optional

class SandboxViolation(Exception): pass

class Sandbox:
    def __init__(self, root: Optional[pathlib.Path] = None):
        self.root = root.resolve() if root else None

    def resolve(self, user_path: str | pathlib.Path) -> pathlib.Path:
        """Resolve a user-supplied path to an absolute path, refusing escapes."""
        if self.root is None:
            return pathlib.Path(user_path).resolve()
        p = (self.root / user_path).resolve()
        # is_relative_to handles symlink resolution because we resolved first
        if not p.is_relative_to(self.root):
            raise SandboxViolation(f"path {user_path} escapes sandbox {self.root}")
        return p

    def open(self, user_path, mode="r"):
        return open(self.resolve(user_path), mode)
Then every file-touching call in muLLM goes through sandbox.resolve(path) instead of Path(path). The config picks up MULLM_SANDBOX_ROOT from env or --sandbox-root CLI flag, with a sensible default of ~/.local/share/mullm or wherever you currently put state.

OS-level sandbox (document, don't enforce):

In your README, give users the firejail one-liner and the Docker option:

bash
# Firejail (Linux only)
firejail --private=/path/to/sandbox --net=none mullm ...

# Or run from a Docker container with read-only mounts
docker run --rm -v /path/to/sandbox:/work:rw mullm:latest ...
Don't try to bundle firejail or implement OS-level sandboxing inside the Python package — that's a maintenance nightmare. Document it as a deployment option for security-conscious users.

Attestation, scanning, and trust signals
VirusTotal is a great low-effort high-signal move. Two ways:

Manual per-release: Upload the wheel to virustotal.com/gui/home/upload after each release, paste the resulting public report URL into your GitHub release notes. Takes 30 seconds.
Automated: VirusTotal has a free API tier (500 requests/day). Add a CI step that uploads on tag push and stores the report URL as a release asset.
Beyond VirusTotal, the trust stack that's becoming standard for security-aware Python packages:

Sigstore signatures: free, automatic with Trusted Publishers (already in the workflow I gave you). Users verify with pip install sigstore && python -m sigstore verify ...
SLSA provenance attestation: automatic with the pypa/gh-action-pypi-publish@release/v1 action when you add attestations: true. This is verifiable proof that the wheel was built by your specific GitHub Actions workflow at a specific commit.
SBOM (Software Bill of Materials): generate with cyclonedx-py or syft, attach to GitHub release. Enterprise buyers expect this now.
Scan reports as release artifacts: have CI emit bandit-report.json, pip-audit.json, semgrep-report.json, trivy-report.json and attach to the release. Even better, fail the build if anything HIGH/CRITICAL appears.
Add a SECURITY.md to the repo that:

Lists all the scanners you run and the cadence
Provides a security contact email (security@0101technology.com)
Documents the responsible disclosure policy (90 days is standard)
Links to the most recent VirusTotal report and SBOM
That package — Sigstore + SLSA + VirusTotal + SBOM + scan reports + SECURITY.md — puts you ahead of 95% of PyPI packages, including most enterprise-backed ones. It's not overkill; it's the new floor for anything touching LLMs.

One note: "badger" — I'm guessing you mean bandit (the Python AST security linter from PyCQA)? If "badger" is something else (Badger DB scanner? a private tool?) ignore me. Either way, add pip-audit (Python vuln scanner) and trivy (broader, can scan wheels and containers) to your stack if you don't have them. Both are free and fast.

License switch to Apache-2.0 — yes, do it, and here's the checklist
Apache-2.0 is the better choice for muLLM than MIT. It gives explicit patent grants (which matters for ML-adjacent infrastructure where patent landscape is messy), and enterprise legal teams are more comfortable with it. The migration checklist:

Replace LICENSE with the full Apache-2.0 text from apache.org/licenses/LICENSE-2.0.txt
Create a NOTICE file: include your copyright line (Copyright 2026 0101 Technology LLC) plus required NOTICE text from any Apache-2.0 dependencies you bundle
Add a header to each source file (Apache convention, not strictly required but expected):
python
   # Copyright 2026 0101 Technology LLC
   # SPDX-License-Identifier: Apache-2.0
Update pyproject.toml: license = "Apache-2.0"
Update README badge and any "MIT" mentions
If you have prior commits attributed to "MIT licensed," that's fine — the project license going forward is Apache-2.0; previous releases don't retroactively change but no one is depending on them yet
Recommended order, given everything above
If you do everything: today / tomorrow, get the 0101technology.com email working (the domain is registered, just need MX + an inbox provider — Migadu in particular has zero approval friction and you can be sending in an hour). With that email plus your real career history, OpenReview profile activates fast. ORCID is 15 minutes, in parallel. Overleaf and template in parallel. By next weekend you have an OpenReview-active profile, an ORCID, the paper in the ACL template, and you can submit the paper that weekend instead of cutting it close.

Mullm release in parallel under Apache-2.0 with the sandbox toggle and the security trust stack — this is independent work, no anonymity entanglement, do it on whatever schedule works.

The 0101technology.com site goes live whenever the form handler is solid; it doesn't gate the paper at all.

If you decide to skip the conference anyway: that's your call. The site + mullm release is still 90% of the value of the next 15 days, and the paper-submission steps I've described are nicely additive (everything you set up — ORCID, OpenReview, the template — keeps working for the Dec 2026 cycle if you change your mind later).

My honest read: do both. The paper isn't the bottleneck you're treating it as.
