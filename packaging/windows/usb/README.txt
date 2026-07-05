μ|LLM — USB Quickstart for Windows (AMD)
=========================================

QUICK TEST (no GPU, no Ollama needed):
  1. Right-click install.ps1 → Run with PowerShell
  2. Double-click start.bat
  3. Open http://127.0.0.1:8100 in your browser
  4. Ask "what is 2+2" → instant (groundtruth, free)
  5. Ask "what is the time complexity of binary search" → instant (groundtruth, free)
  6. Ask something complex → routes to cloud (needs API key)

ADD GPU ACCELERATION (AMD ROCm):
  1. Download AMD HIP SDK 6.1+ from:
       https://www.amd.com/en/developer/resources/rocm-hub/hip-sdk.html
  2. Install HIP SDK, restart
  3. Run: powershell -ExecutionPolicy Bypass -File install.ps1 -Ollama -ROCm
  4. Ollama will auto-detect your AMD GPU
  5. Double-click start.bat — local inference now uses GPU (~30-60 tok/s on RX 6000/7000)

WITHOUT ROCm:
  - Groundtruth cache: instant (free) — covers ~40% of common queries
  - Cloud routing: works with your Anthropic/OpenAI key
  - Local inference: possible via CPU (~2-5 tok/s — slow but functional)

SUPPORTED AMD GPUs:
  RX 6600 / 6700 / 6800 / 6900 series
  RX 7600 / 7700 / 7800 XT / 7900 series
  Radeon PRO W6000 / W7000 series

NOTES:
  - TRELLIS inference won't conflict (different port)
  - muLLM runs on port 8100
  - All data stays local (scoring_log.jsonl in cache/)
