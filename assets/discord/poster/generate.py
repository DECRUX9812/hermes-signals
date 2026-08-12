#!/usr/bin/env python3
"""Retro feature-announcement poster generator (warm-paper templates).

Renders a JSON spec into an HTML template and screenshots it with a headless
browser. Browser resolution order (the Firefox SWGL compositor is broken on
some VMs, so chromium headless-shell is preferred):

    1. Playwright cached chromium headless-shell
    2. Playwright cached chromium
    3. chromium / chromium-browser / google-chrome
    4. firefox

Usage:
    python3 generate.py spec.json -o poster.png [--template template.html]
"""
import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(HERE, "template.html")
CANVAS = "1200,900"

# ---- icon library: name -> SVG inner markup (24x24 stroke line icons) ----
ICONS = {
    "wrench": '<path d="M14.5 6.5a4 4 0 0 0-6.7-2.9L10 6 8 8 6.2 6.2A4 4 0 1 0 11.5 12L20 20.5l2-2L13.5 10a4 4 0 0 0 1-3.5z"/><path d="M19.5 2.5l2 2"/>',
    "rocket": '<path d="M12 2c3 1.2 5 3.8 5 7.5V13l3 3v2h-5l-1.5 4h-3L9 18H4v-2l3-3V9.5C7 5.8 9 3.2 12 2z"/><circle cx="12" cy="8" r="2"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
    "doc": '<path d="M6 2h8l4 4v16H6z"/><path d="M14 2v4h4"/>',
    "flask": '<path d="M10 2v6l-6 11a2 2 0 0 0 1.8 3h12.4a2 2 0 0 0 1.8-3L14 8V2"/><path d="M8 2h8"/><path d="M7 15h10"/>',
    "gauge": '<path d="M12 14l4.5-4.5"/><path d="M4 18a8 8 0 1 1 16 0"/>',
    "scale": '<path d="M12 4v16"/><path d="M7 20h10"/><path d="M5 8h14"/><path d="M5 8l-3 6a3 3 0 0 0 6 0z"/><path d="M19 8l-3 6a3 3 0 0 0 6 0z"/>',
    "terminal": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 9l3 3-3 3"/><path d="M13 15h4"/>',
    "file": '<path d="M6 2h8l4 4v16H6z"/><path d="M9 12h6M9 15.5h6"/>',
    "sliders": '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="15" cy="12" r="2"/><circle cx="7" cy="18" r="2"/>',
    "search": '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.5-4.5"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M19.1 4.9L17 7M7 17l-2.1 2.1"/>',
    "people": '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.5 2.9-5.5 6.5-5.5s6.5 2 6.5 5.5"/><circle cx="17" cy="9" r="2.5"/><path d="M16 14.5c3 .4 5.5 2.2 5.5 5.5"/>',
    "shield": '<path d="M12 2l8 3v6c0 5-3.5 8.5-8 11-4.5-2.5-8-6-8-11V5z"/>',
    "trend": '<path d="M3 7l6 6 4-4 8 8"/><path d="M21 12v5h-5"/>',
    "check": '<circle cx="12" cy="12" r="9"/><path d="M8.5 12.5l2.5 2.5 5-5"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "tokens": '<ellipse cx="12" cy="6" rx="8" ry="3"/><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6"/><path d="M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
    "star": '<path d="M12 3l2.5 5.5L20 9l-4 4 1 6-5-3-5 3 1-6-4-4 5.5-.5z"/>',
    "branch": '<circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="9" r="2.5"/><path d="M6 8.5v7M8.5 6.5c2.5 0 2.5 2 4.5 2.5"/>',
    "tag": '<path d="M3 3h7l11 11-7 7L3 10z"/><circle cx="8.5" cy="8.5" r="1.5"/>',
    "link": '<path d="M10 14l4-4"/><path d="M8 12l-3 3a4 4 0 0 0 6 6l3-3"/><path d="M16 12l3-3a4 4 0 0 0-6-6l-3 3"/>',
    "cpu": '<rect x="7" y="7" width="10" height="10" rx="1.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.5 4.5l2 2M17.5 17.5l2 2M19.5 4.5l-2 2M6.5 17.5l-2 2"/>',
    "eye": '<path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6z"/><circle cx="12" cy="12" r="3"/>',
}


def find_browser() -> str:
    """Pick a working headless browser binary."""
    for pattern in (
        os.path.expanduser("~/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell"),
        os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome"),
    ):
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    for name in ("chromium-browser", "chromium", "google-chrome", "firefox"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("no headless browser found (tried chromium headless-shell, chromium, firefox)")


def _screenshot_cmd(browser: str, out_abs: str, url: str) -> list[str]:
    if "chrome" in browser or "chromium" in browser:
        return [
            browser,
            "--headless", "--disable-gpu", "--no-sandbox",
            f"--screenshot={out_abs}",
            f"--window-size={CANVAS}",
            url,
        ]
    return [
        browser,
        "--headless", "--screenshot", out_abs,
        "--window-size", CANVAS,
        url,
    ]


# ---- tiny template engine: {{KEY}} and {{#LIST}}...{{/LIST}} ----
LOOP_RE = re.compile(r"\{\{#(\w+)\}\}(.*?)\{\{/\1\}\}", re.S)
TOKEN_RE = re.compile(r"\{\{([\w.]+)\}\}")


def render(template, ctx):
    def loop_repl(m):
        name, inner = m.group(1), m.group(2)
        items = ctx.get(name, [])
        out = []
        for item in items:
            ic = dict(ctx)
            if isinstance(item, dict):
                ic.update(item)
                out.append(render(inner, ic))
            else:
                ic["."] = item
                out.append(render(inner, ic))
        return "".join(out)

    def token_repl(m):
        key = m.group(1)
        if key in ctx:
            return str(ctx[key])
        return m.group(0)

    for _ in range(6):
        t = LOOP_RE.sub(loop_repl, template)
        if t == template:
            break
        template = t
    return TOKEN_RE.sub(token_repl, template)


def expand_icons(spec):
    def expand(name):
        body = ICONS.get(name, ICONS["star"])
        return f'<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'

    for s in spec.get("STEPS", []):
        s["ICON"] = expand(s["ICON"])
    for r in spec.get("ROWS", []):
        r["ICON"] = expand(r["ICON"])
    for st in spec.get("STATS", []):
        st["ICON"] = expand(st["ICON"])
    for f in spec.get("FOOTER", []):
        f["ICON"] = expand(f["ICON"])
    return spec


def main():
    ap = argparse.ArgumentParser(description="Retro feature-announcement poster")
    ap.add_argument("spec", help="JSON spec file")
    ap.add_argument("-o", "--output", default="poster.png")
    ap.add_argument(
        "--template",
        default=TEMPLATE_PATH,
        help="HTML template (default: navy command-center template.html)",
    )
    args = ap.parse_args()

    with open(args.spec, encoding="utf-8") as f:
        spec = json.load(f)
    with open(args.template, encoding="utf-8") as f:
        tpl = f.read()

    spec = expand_icons(spec)
    html_out = render(tpl, spec)

    html_path = os.path.splitext(args.output)[0] + ".html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_out)

    out_abs = os.path.abspath(args.output)
    url = "file://" + os.path.abspath(html_path)
    browser = find_browser()
    cmd = _screenshot_cmd(browser, out_abs, url)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(1)
    size = os.path.getsize(args.output) if os.path.exists(args.output) else 0
    if size == 0:
        print(f"ERROR: {args.output} empty/absent after render (browser: {browser})", file=sys.stderr)
        sys.exit(1)
    print(f"rendered {args.output} ({size} bytes, {os.path.basename(browser)})")


if __name__ == "__main__":
    main()
