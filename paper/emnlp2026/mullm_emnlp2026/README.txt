muLLM EMNLP 2026 Submission Package
====================================

Files:
  mullm_paper.tex         - LaTeX source (ACL review-mode, anonymized)
  mullm_paper.pdf         - Compiled PDF (8 pages, what you upload to OpenReview)
  mullm_references.bib    - Bibliography (18 entries, all cited)
  acl.sty                 - ACL style file
  acl_natbib.bst          - ACL bibliography style

To recompile:
  pdflatex mullm_paper
  bibtex mullm_paper
  pdflatex mullm_paper
  pdflatex mullm_paper

For ARR/EMNLP submission via OpenReview:
  - Upload mullm_paper.pdf as the main paper
  - Optionally upload this entire ZIP as supplementary material
  - Bind venue: EMNLP 2026
  - Preprint policy: non-binding
  - Cycle: ARR May 2026

Page structure (8 pages total):
  Pages 1-4: Main content (Intro, Related Work, System, Evaluation)
  Page 5:    End of evaluation + Conclusion + References start
  Page 6:    References (18) + Limitations
  Page 7:    Ethical Considerations + Appendix A start (mμPETS)
  Page 8:    Appendix B (A/B), C (Classifier Alternatives), D (mμPQS)

Validation: passes aclpubcheck content checks.
  - 543 line-number "errors" are expected in [review] mode
  - 14 page-number "errors" are stripped at camera-ready
  - 0 actual content overflow errors

Anonymization: verified clean. No author names, GitHub URLs, or
identifying details. Acknowledgments redacted; generic AI assistance
disclosure per ACL policy.
