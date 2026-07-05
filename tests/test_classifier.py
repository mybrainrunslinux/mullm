#!/usr/bin/env python3
"""
Classifier Eval Suite — Tests the intent classifier against known-good samples.
Usage: python3 test_classifier.py [--url http://localhost:8800]

Requires the router to be running. Tests classification accuracy
against your validated ground truth.
"""

import argparse
import json
import sys
import time

import httpx

# ---------------------------------------------------------------------------
# Ground truth samples — YOU validate these. Add more to reach 50-100.
# Format: (input_text, expected_category, expected_complexity_range, notes)
# ---------------------------------------------------------------------------

GROUND_TRUTH: list[dict[str, object]] = [
    # === NOTE (save/store/bookmark) ===
    {
        "input": "Save these three URLs somewhere and also here is a screenshot related to them. I'd like to maybe blog about this later, I just need to find it.",
        "expected_category": "note",
        "expected_complexity_max": 2,
        "notes": "Save + bookmark + screenshot = note, not code",
    },
    {
        "input": "Remind me to check on the quail eggs tomorrow morning.",
        "expected_category": "note",
        "expected_complexity_max": 1,
        "notes": "Simple reminder/note",
    },
    {
        "input": "Here's an interesting arxiv link about agent memory sharing compression, save it for the team to review later.",
        "expected_category": "note",
        "expected_complexity_max": 2,
        "notes": "Bookmarking a link with context",
    },
    # === LOOKUP (simple fact retrieval) ===
    {
        "input": "What is the capital of France?",
        "expected_category": "lookup",
        "expected_complexity_max": 1,
        "notes": "Trivial fact",
    },
    {
        "input": "What port does Redis use by default?",
        "expected_category": "lookup",
        "expected_complexity_max": 1,
        "notes": "Quick tech fact",
    },
    # === CODE (write/fix/build software) ===
    {
        "input": "This game looks cool I grabbed a screenshot and a short recording, optimize the files for size and save them.",
        "expected_category": "code",
        "expected_complexity_max": 2,
        "notes": "Simple file optimization script",
    },
    {
        "input": "Give me a simple photo-overlay app where I can quickly recolor greyscale basic blur maybe lightweight effects and export a JPEG or maybe PNG or the composition/new image.",
        "expected_category": "code",
        "expected_complexity_max": 5,
        "notes": "Full app build — complex code",
    },
    {
        "input": "Write a script to scrape headlines from five news sites.",
        "expected_category": "code",
        "expected_complexity_max": 3,
        "notes": "Medium code task",
    },
    {
        "input": "Refactor this legacy Python function for modern async usage.",
        "expected_category": "code",
        "expected_complexity_max": 4,
        "notes": "Refactoring task",
    },
    {
        "input": "Here is a napkin sketch of an architecture diagram. Build what it describes or as much as you can for an MVP or POC.",
        "expected_category": "code",
        "expected_complexity_max": 5,
        "notes": "Build from sketch — max complexity",
    },
    # === RESEARCH (investigate/compare/analyze/translate) ===
    {
        "input": "Here is a digital sketch of an architecture diagram, save it in a way I can search for text in it like Redis or Ravine later.",
        "expected_category": "research",
        "expected_complexity_max": 3,
        "notes": "OCR + indexing = research/processing, not just note",
    },
    {
        "input": "Summarize the key points of this PDF document for my presentation.",
        "expected_category": "research",
        "expected_complexity_max": 3,
        "notes": "Document analysis",
    },
    {
        "input": "Search for current news on renewable energy in Europe.",
        "expected_category": "research",
        "expected_complexity_max": 3,
        "notes": "Web research",
    },
    {
        "input": "Translate this image of a document into Spanish.",
        "expected_category": "research",
        "expected_complexity_max": 3,
        "notes": "OCR + translation",
    },
    {
        "input": "Plan a 3-day trip to Tokyo with budget constraints.",
        "expected_category": "research",
        "expected_complexity_max": 4,
        "notes": "Planning research",
    },
    {
        "input": "Compare the performance characteristics of Redis vs Valkey vs DragonflyDB for our pub/sub use case.",
        "expected_category": "research",
        "expected_complexity_max": 4,
        "notes": "Technical comparison research",
    },
    # === CREATIVE (design/write/art) ===
    {
        "input": "Design a game about keeping quail, simple cute cartoony with a bit of strategic depth only for those who want it, something we want to play daily and somewhat accurate to permaculture coturnix quail keeping.",
        "expected_category": "creative",
        "expected_complexity_max": 5,
        "notes": "Game design — creative, not code (no 'build' keyword)",
    },
    {
        "input": "Write a haiku about a rainy afternoon.",
        "expected_category": "creative",
        "expected_complexity_max": 2,
        "notes": "Simple creative writing",
    },
    # === DEPLOY (infra/servers/containers) ===
    {
        "input": "Create a Containerfile and podman-compose for this microservice.",
        "expected_category": "deploy",
        "expected_complexity_max": 4,
        "notes": "Container setup — deploy category",
    },
    {
        "input": "Develop a full-stack multi-panel real-time communication app with voice chat, video, screen sharing, and user management using WebRTC, WebSockets, and Redis pub/sub.",
        "expected_category": "code",  # or deploy — either acceptable
        "expected_complexity_max": 5,
        "notes": "Massive full-stack build",
    },
    # === CONVERSATION (greeting/meta) ===
    {
        "input": "Hello, how are you doing today?",
        "expected_category": "conversation",
        "expected_complexity_max": 1,
        "notes": "Simple greeting",
    },
    {
        "input": "What can you help me with?",
        "expected_category": "conversation",
        "expected_complexity_max": 1,
        "notes": "Meta question about capabilities",
    },
]


def run_eval(base_url: str, verbose: bool = True):
    """Run the eval suite against the running router."""
    print(f"\n{'=' * 70}")
    print(f"  Classifier Eval Suite — {len(GROUND_TRUTH)} samples")
    print(f"  Target: {base_url}")
    print(f"{'=' * 70}\n")

    correct = 0
    wrong = []
    total_ms = 0

    with httpx.Client(timeout=60.0) as client:
        for i, sample in enumerate(GROUND_TRUTH, 1):
            try:
                r = client.post(f"{base_url}/classify", json={"content": sample["input"]})
                r.raise_for_status()
                result = r.json()
                classification = result["classification"]

                got_category = classification["category"]
                got_complexity = classification["complexity"]
                elapsed = result["elapsed_ms"]
                total_ms += elapsed

                # Check category match
                cat_match = got_category == sample["expected_category"]
                # Check complexity is within range
                comp_match = got_complexity <= sample["expected_complexity_max"]

                if cat_match and comp_match:
                    correct += 1
                    status = "✅"
                elif cat_match:
                    correct += 1  # category right is what matters most
                    status = "⚠️ "  # complexity off but category right
                else:
                    status = "❌"
                    wrong.append(
                        {
                            "index": i,
                            "input": str(sample["input"])[:60],
                            "expected": sample["expected_category"],
                            "got": got_category,
                            "notes": sample["notes"],
                        }
                    )

                if verbose:
                    print(
                        f"  [{i:2d}] {status} "
                        f"expect={sample['expected_category']:12s} "
                        f"got={got_category:12s} "
                        f"cx={got_complexity} "
                        f"conf={classification['confidence']:.2f} "
                        f"({elapsed:.0f}ms)"
                    )
                    if not cat_match:
                        print(f"       ^ {sample['notes']}")

            except Exception as e:
                print(f"  [{i:2d}] 💥 ERROR: {e}")
                wrong.append({"index": i, "input": str(sample["input"])[:60], "error": str(e)})

    # Summary
    accuracy = correct / len(GROUND_TRUTH) * 100 if GROUND_TRUTH else 0
    avg_ms = total_ms / len(GROUND_TRUTH) if GROUND_TRUTH else 0

    print(f"\n{'=' * 70}")
    print(f"  Results: {correct}/{len(GROUND_TRUTH)} correct ({accuracy:.1f}%)")
    print(f"  Avg latency: {avg_ms:.0f}ms per classification")
    print(f"  Total time: {total_ms / 1000:.1f}s")

    if wrong:
        print(f"\n  Misclassified ({len(wrong)}):")
        for w in wrong:
            print(
                f"    [{w['index']}] expected={w.get('expected', '?')} "
                f"got={w.get('got', 'ERROR')} — {w.get('notes', w.get('error', ''))}"
            )

    if accuracy >= 90:
        print("\n  🎯 Great — 90%+ accuracy. Classifier is solid.")
    elif accuracy >= 75:
        print("\n  🟡 Decent — might need prompt tuning for edge cases.")
    else:
        print("\n  🔴 Needs work — review misclassified samples and adjust prompt.")

    print(f"{'=' * 70}\n")
    return accuracy


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test the pipeline classifier")
    parser.add_argument("--url", default="http://localhost:8800", help="Router URL (default: http://localhost:8800)")
    parser.add_argument("-q", "--quiet", action="store_true", help="Only show summary")
    args = parser.parse_args()

    run_eval(args.url, verbose=not args.quiet)
