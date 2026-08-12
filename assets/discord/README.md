# Discord share assets

- `hermes-signals-how.png` — 1600×1200 narrative poster: agent says done →
  the trace shows failure → FALSE SUCCESS. Use for launches/sharing.
- `hermes-signals-install.png` — 1600×1200 how-to poster: two commands, then
  done. Use for onboarding/quickstarts.
- `create_infographic.py` — deterministic Pillow renderer for both posters.

Self-contained: system fonts only, no remote assets. Regenerate with:

```bash
python3 assets/discord/create_infographic.py
```
