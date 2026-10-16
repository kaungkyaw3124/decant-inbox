"""AI helper (docs/SPEC-v4.6-ai.md): the AI only UNDERSTANDS customer messages for the web
app. It never talks to customers, never invents products; replies still come from our
templates and prices. Results are checked by our code (checker.py) before anything uses them.

  settings.py   mode OFF / SHADOW / AUTO, caps, budget, threshold (app_settings "ai")
  prompt.py     catalog + instructions (static, cached) and the message context (dynamic)
  privacy.py    phones / addresses / long numbers masked before anything leaves the server
  providers.py  openai (real) and fake (tests)
  checker.py    product ids, sizes, quantities, learn texts
  service.py    when to call, ai_calls bookkeeping, AUTO mode
  hints.py      SHADOW mode: the AI's answers pre-selected on the teaching card
"""
