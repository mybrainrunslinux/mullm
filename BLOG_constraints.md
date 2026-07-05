# Blog Post Plan: Why `pip install mullm` Isn't the Whole Story

_Target: mullm.com/blog or dev.to / Hacker News — Python/security-adjacent audience_
_Estimated length: 1,200–1,800 words. No fluff. Every section earns its place._

---

## Working title options
- "The one-liner that security-conscious Python packages can't use"
- "Why we couldn't just say `pip install mullm`"
- "`pip install` is not enough: CVEs, constraints, and the gap nobody talks about"

---

## The hook (opening, ~150 words)

You've built a wheel. It's clean. You've checked your direct deps. You're proud of it.
Then someone installs it into an environment with `requests==2.31.0` already present —
CVE-2024-35195, proxy credentials leaking to attackers. Your wheel said `requests>=2.28`.
That's satisfied. The CVE is present. `pip install yourpackage` worked perfectly.

muLLM sits in front of API keys and routes real money. We cared about this more than average.
Here's what we found, what we did, and why more package authors should do it.

---

## Section 1: How pip's resolver actually works (and the gap it leaves)

**Key points:**
- `install_requires` in your wheel specifies your *direct* deps with version bounds
- pip resolves the full dep graph — including transitive deps you never asked for
- If a vulnerable version already exists in the environment and satisfies the graph, pip uses it
- pip does not upgrade installed packages just because a new dep would prefer a newer version
- Your wheel is clean. The resolved environment is not. These are different things.

**Concrete example to include:**
```
# wheel says:
install_requires = ["litellm>=1.83.0"]

# litellm says:
install_requires = ["requests>=2.20.0"]   # very loose

# user's environment already has:
requests==2.31.0   # CVE-2024-35195

# result: pip install mullm -- succeeds. CVE present.
```

---

## Section 2: What `constraints.txt` actually is (vs requirements.txt)

**The three mechanisms — most developers only know one or two:**

| File | Purpose | When it runs |
|------|---------|-------------|
| `install_requires` (in wheel) | Declares direct dep bounds | Embedded in the package |
| `requirements.txt` | Specifies what to install | `pip install -r` |
| `constraints.txt` | Overrides version resolution | `pip install -c` |

**Key distinction to drive home:**
- `requirements.txt` says "install these packages"
- `constraints.txt` says "when resolving anything, never go below these versions" — it applies to the *entire resolution*, including transitive deps you didn't name
- It does not install extra packages. It just sets a floor on what versions are acceptable.
- This is the only pip mechanism that can enforce transitive dep security.

---

## Section 3: The 6 CVEs in muLLM's dep graph (make it concrete)

This is what we found. Real CVE numbers. Reproducible.

| Package | Vulnerable below | CVE | What it does |
|---------|-----------------|-----|-------------|
| `python-jose` | 3.5.0 | CVE-2024-33663 | Algorithm confusion — JWT tokens can be forged |
| `GitPython` | 3.1.50 | CVE-2024-22190 | Remote code execution via crafted repo path |
| `Pillow` | 12.2.0 | CVE-2025-* (several) | Image parsing buffer issues |
| `requests` | 2.33.0 | CVE-2024-35195 | Proxy credentials leaked to redirect targets |
| `urllib3` | 2.6.3 | CVE-2024-37891 | Proxy-Authorization header sent to wrong host |
| `litellm` | 1.83.14 | internal patches | Multiple security fixes across minor versions |

**Why these matter for muLLM specifically:**
- This tool proxies API keys (Anthropic, OpenAI, Google)
- `requests`/`urllib3` CVEs in a proxy tool = potential key exfiltration
- `python-jose` is used in auth flows — algorithm confusion = impersonation
- `GitPython` is a transitive dep from tooling — RCE is RCE

---

## Section 4: The solution — constraints.txt + install-venv.sh

Show the actual files. They're short.

`constraints.txt` (11 lines including comments):
```
python-jose>=3.5.0
GitPython>=3.1.50
Pillow>=12.2.0
requests>=2.33.0
urllib3>=2.6.3
litellm>=1.83.14
```

Install command:
```bash
pip install -c constraints.txt mullm-1.0.0-py3-none-any.whl
```

`install-venv.sh` — the opinionated answer for users who want a clean, verified install:
- Creates a fresh venv
- Installs wheel + constraints in one pass
- Prints installed versions for manual verification
- 30 lines of shell. No magic.

**The cost:** one extra flag. One extra file. That's it.

---

## Section 5: Why wheels can't solve this themselves

**Important: this is not a pip bug or a packaging failure.**

Wheels cannot enforce transitive dep versions by design — that would make the package
ecosystem fragile and break composability. If every package hardcoded exact transitive
versions, you'd have constant conflicts when combining packages.

The boundary is intentional:
- Wheels declare what they *need*
- Constraints declare what the *environment* must satisfy
- These are different layers, and they should be

The gap exists because most packages don't care enough to close it.
Security-sensitive packages should.

---

## Section 6: What this means for package authors

**Practical takeaways:**
1. Run `pip-audit` or Grype on your installed venv — not just your source
2. If any transitive dep has a CVE, write a `constraints.txt` with the patched lower bound
3. Ship `install-venv.sh` or equivalent for users who want a verified path
4. Don't feel bad that `pip install yourpackage` isn't perfectly secure alone — pip wasn't designed to make it so. Document the gap.

**The honest tradeoff:**
- Simpler install UX: `pip install mullm` — works, but leaves CVE exposure
- Secure install: `pip install -c constraints.txt mullm-1.0.0-py3-none-any.whl` — one more thing to explain
- We chose the second and explained it. That's the whole blog post.

---

## Closing (~100 words)

The best security story is a true one. muLLM routes real money through real API keys.
We wanted to be able to say: "here are the exact CVEs, here is what closes them, here
is the install path that verifies it." That's what `constraints.txt` + `install-venv.sh` gives us.

It's not heroic. It's a 11-line text file and a 30-line shell script.
Most packages skip it. They probably should not.

---

## Notes / assets to gather before writing final draft

- [ ] Confirm CVE numbers are correct and still current when post publishes (CVEs don't change but patches might advance)
- [ ] Run `pip-audit` on fresh install to screenshot output (good visual)
- [ ] Consider linking to pip constraints docs (they exist but are buried)
- [ ] Consider cross-posting: dev.to, HN Show HN, Python subreddit
- [ ] Timing: publish *after* paper submission (May 25) so paper is the first public artifact
