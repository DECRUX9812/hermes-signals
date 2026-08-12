# Discord share assets

- `hermes-signals-how.png` — 1200×900 warm-paper narrative poster: agent says
  done → the trace shows failure → FALSE SUCCESS. Use for launches/sharing.
- `hermes-signals-install.png` — 1200×900 warm-paper how-to poster: two
  commands, then done. Use for onboarding/quickstarts.

Both are rendered from HTML/CSS specs (pixel-exact text) via the vendored
pipeline in `poster/` — no image models, no remote assets:

```bash
cd assets/discord/poster
python3 generate.py spec-hero.json    -o ../hermes-signals-how.png     --template template-warm-hero.html
python3 generate.py spec-install.json -o ../hermes-signals-install.png --template template-warm-hero.html
```

The renderer auto-detects a headless browser (Playwright chromium
headless-shell → chromium → firefox). Firefox's SWGL compositor is broken on
some VMs — prefer the chromium headless shell binary.
