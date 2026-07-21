"""
ClinicalPilot — Hardcoded secrets (OPTIONAL)
=============================================

Copy this file to `secrets.local.py` (same folder) and fill in any keys you want
hardcoded. `secrets.local.py` is gitignored and will NEVER be committed.

Resolution order for every key the app needs:

    1. Hardcoded here (this file)  ── if set, it is used and the user is NEVER asked
    2. Environment / .env          ── same effect as hardcoding
    3. Entered in the UI at runtime ── stored in memory only, cleared on restart
    4. None of the above           ── the app asks the user for it on demand

So: hardcode a key here and that provider "just works" with zero prompts.
Leave a key empty ("") and the app will ask for it in the UI when it's first needed.

The dictionary key is the `api_key_ref` used by a profile in config/models.json.
You can add any custom key name your own profiles reference (e.g. "OPENROUTER_KEY").
"""

HARDCODED_KEYS = {
    # --- Cloud engines -------------------------------------------------------
    "OPENAI_API_KEY": "",          # e.g. "sk-..."
    "GROQ_API_KEY": "",            # e.g. "gsk_..."
    "ANTHROPIC_API_KEY": "",       # e.g. "sk-ant-..."

    # --- Any OpenAI-compatible endpoint (OpenRouter, vLLM, Together, a gateway…)
    # "OPENROUTER_KEY": "",
    # "MY_GATEWAY_KEY": "",
}

# Optional: hardcode base-URL overrides here too (by api_key_ref-style logical name).
# These override the base_url set on a profile in config/models.json when present.
HARDCODED_BASE_URLS = {
    # "OLLAMA_BASE_URL": "http://localhost:11434",
}
