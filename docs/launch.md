# Launch plan

Ground truth for a Show HN / community launch. Every claim below is either
verified research (sourced) or reproducible from this repo (run it yourself).
Do not add numbers that aren't in this file or in the corpus — a single
fabricated stat will sink the launch.

## The hook (verified register)

The pain is a **named category**, not an anecdote:

- Kayla Mathisen, Mar 2026 — *"I rotate between 18 agents daily. None of them
  know this dashboard exists."* ([substack](https://kaylarosemathisen.substack.com/p/my-ai-agents-lie-about-their-status) · [HN 47249964](https://news.ycombinator.com/item?id=47249964))
- [Ask HN: "The agent lied to you, how will you handle it?"](https://news.ycombinator.com/item?id=43512740)
- MIT Technology Review, Aug 2026 — [Why AI agents lie and cheat to reach their goals](https://www.technologyreview.com/2026/08/03/1141009/heres-why-ai-agents-lie-and-cheat-to-reach-their-goals/)
- Mistral Leanstral — launched on "trustworthy coding", ~780 HN points ([HN 47404796](https://news.ycombinator.com/item?id=47404796))

## Show HN title options (pick one)

1. **Show HN: I built the hidden monitor for AI agents — it catches "done" being a lie**
2. **Show HN: My agent said "successfully updated" — the tool had timed out. So I built a trace cop**
3. **Show HN: Agent quality layer that needs no API key, no model, no telemetry — it reads the traces you already have**

Title 2 mirrors the verified substack register that resonated; title 3 leads
with the zero-setup contrast (the strongest viral pattern from the research).

## Post skeleton

1. **The betrayal, in one paragraph** — agent said done, tool failed; repeat
   until you've shipped a lie. Cite the Ask HN thread + substack as proof you're
   not alone.
2. **What I built** — a deterministic trace scanner: 8 failure-mode signals
   (false-success, retry-loop, unverified-change, secret-risk,
   subagent-handoff-loss, hallucinated-evidence, instruction-drift,
   cost-runaway). Zero model calls. Zero network. Zero API key.
3. **The kicker: it reads traces you already have** — Hermes `state.db`,
   OpenCode SQLite, Claude Desktop JSONL, or any JSON trace. No SDK, no
   decorator, no migration. **No other tool in the OSS landscape does this**
   (verified: Langfuse/Phoenix/OpenLIT/Weave/TruLens all require
   instrumentation first; none read session stores in place).
4. **The demo** — one command: `hermes signals scan <trace>`. Ship the corpus
   as the reproducible example (12 traces, labels in `labels.json`).
5. **Honest limits** — deterministic ≠ omniscient: signals are review
   candidates, not verdicts; the optional judge stage is off by default; false
   positives are welcome bug reports (they improve the corpus).
6. **CTA** — install (`hermes plugins install DECRUX9812/hermes-signals
   --enable && hermes signals setup`), label what you see, report false
   positives, join the Nous Discord `#plugins-skills-and-skins`.

## The benchmark writeup (the virality vehicle)

Comparison/evidence posts are the proven pattern. Skeleton for a follow-up post:

> "What 10 real sessions hid from me — and how a deterministic trace scan
> caught them"

- Backfill your real Hermes/OpenCode/Claude sessions (`hermes signals backfill`),
  then `hermes signals report`.
- Per signal: how many matched, how many you confirmed as real after review,
  how many were false positives (label via `hermes signals feedback`).
- The numbers in the post must come from your real store — regenerate the
  report the same day you post, don't guess.
- Never quote a "tests passed but didn't" anecdote as verified — no fetchable
  source was found during research (subagent marked it unverified).

## Distribution checklist

- [ ] Show HN in the "lied/done" register (title 2 or 3)
- [ ] Discord: Nous Research `#plugins-skills-and-skins` + r/LocalLLaMA + r/ClaudeAI (share the poster)
- [ ] GitHub Discussions seeded with 2-3 threads (false-positive reports, integration requests)
- [ ] README poster asset linked in the post (assets/discord/hermes-signals-discord.png)
- [ ] Issues: label `good first issue` (new backfill sources: Cline, Aider; webhook reporter)
- [ ] Watch the precision report: post a follow-up at 1 week with real labeled numbers
