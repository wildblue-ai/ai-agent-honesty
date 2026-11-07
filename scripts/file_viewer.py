"""Generate one read-only HTML viewer page per project file linked from the dashboard.

Chrome downloads .yaml from file:// instead of showing it, so the dashboard links to these pages.
They are derived output, rebuilt from the real file on every dashboard build.
"""
from __future__ import annotations

import hashlib
import html
import re
import shutil
from datetime import datetime
from pathlib import Path

import markdown

e = html.escape

PAGE_CSS = """
:root{--bg:#f5f6f3;--surface:#fff;--ink:#1d2421;--muted:#5f6b66;--line:#dde2de;--accent:#2f5d50;--key:#2f5d50;--str:#8a4b1f;--com:#7d8a84;--num:#3b6fb6;
--mono:"JetBrains Mono",ui-monospace,Menlo,monospace;--body:"Public Sans",system-ui,sans-serif}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#141917;--surface:#1c2320;--ink:#e4ebe7;--muted:#9aa7a1;--line:#2d3732;--accent:#8fc4b2;--key:#8fc4b2;--str:#e8b07e;--com:#7f8c86;--num:#7ea6e6;color-scheme:dark}}
:root[data-theme="dark"]{--bg:#141917;--surface:#1c2320;--ink:#e4ebe7;--muted:#9aa7a1;--line:#2d3732;--accent:#8fc4b2;--key:#8fc4b2;--str:#e8b07e;--com:#7f8c86;--num:#7ea6e6;color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 var(--body)}
.wrap{max-width:1100px;margin:0 auto;padding-block:20px 40px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
a{color:var(--accent)}
header{display:flex;flex-wrap:wrap;gap:6px 18px;align-items:baseline;margin-bottom:14px}
h1{font:600 1.05rem var(--mono);margin:0;overflow-wrap:anywhere}
.meta{color:var(--muted);font-size:.85rem;display:flex;flex-wrap:wrap;gap:4px 16px}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:8px;overflow:hidden}
pre{margin:0;padding:14px 0;font:.82rem/1.6 var(--mono);counter-reset:ln}
/* Word wrap: each line is a two-column grid, so wrapped text stays aligned right of its line number. */
pre .l{display:grid;grid-template-columns:3.2em minmax(0,1fr);column-gap:14px;padding-right:16px}
pre .l::before{counter-increment:ln;content:counter(ln);text-align:right;color:var(--com);user-select:none}
pre .t{white-space:pre-wrap;overflow-wrap:anywhere;min-width:0}
.k{color:var(--key);font-weight:600}.s{color:var(--str)}.c{color:var(--com);font-style:italic}.n{color:var(--num)}
.prose{padding:18px 22px}.prose table{border-collapse:collapse;display:block;overflow-x:auto}.prose td,.prose th{border:1px solid var(--line);padding:4px 8px}
.prose pre{background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:10px 12px}
code{font-family:var(--mono)}
"""

_KEY = re.compile(r"^(\s*-?\s*)([A-Za-z0-9_'\"\-\.]+)(:)(\s|$)")


def _highlight_yaml_line(line: str) -> str:
    # Split off a trailing comment that is not inside quotes (good enough for these files).
    code, comment = line, ""
    if "#" in line:
        idx = [i for i, ch in enumerate(line) if ch == "#" and (i == 0 or line[i - 1] in " \t")
               and line[:i].count("'") % 2 == 0 and line[:i].count('"') % 2 == 0]
        if idx:
            code, comment = line[:idx[0]], line[idx[0]:]
    out = e(code)
    m = _KEY.match(code)
    if m:
        rest = code[m.end():]
        out = e(m.group(1)) + f'<span class="k">{e(m.group(2))}</span>{m.group(3)}{e(m.group(4))}' + _value(rest)
    else:
        out = _value(code)
    return out + (f'<span class="c">{e(comment)}</span>' if comment else "")


def _value(v: str) -> str:
    s = v.strip()
    if not s:
        return e(v)
    if (s[0] in "'\"" and s[-1] == s[0]):
        return e(v).replace(e(s), f'<span class="s">{e(s)}</span>', 1)
    if re.fullmatch(r"-?\d+(\.\d+)?", s) or s in ("true", "false", "null"):
        return e(v).replace(e(s), f'<span class="n">{e(s)}</span>', 1)
    return e(v)


def viewer_name(rel: str) -> str:
    return rel.replace("/", "__") + ".html"


def write_viewers(root: Path, rels: set[str], out_dir: Path) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)  # derived output only; rebuilt from the real files below
    out_dir.mkdir(parents=True)
    for rel in sorted(rels):
        f = root / rel
        if not f.is_file():
            continue
        data = f.read_bytes()
        text = data.decode("utf-8", errors="replace")
        st = f.stat()
        # Prompt templates show raw text, character for character; other Markdown is rendered.
        is_prompt = rel.startswith("prompts/") and rel not in ("prompts/REVIEW_v1.md", "prompts/CHANGELOG.md")
        if f.suffix == ".md" and not is_prompt:
            body = f'<div class="prose">{markdown.markdown(text, extensions=["tables", "fenced_code"])}</div>'
        else:
            lines = text.splitlines()
            hl = _highlight_yaml_line if f.suffix in (".yaml", ".yml") else e
            body = "<pre>" + "".join(f'<span class="l"><span class="t">{hl(l)}</span></span>' for l in lines) + "</pre>"
        page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(f.name)}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono&family=Public+Sans:wght@400;600&display=swap">
<style>{PAGE_CSS}</style></head><body><div class="wrap">
<header><h1>{e(rel)}</h1><a href="../index.html#files">Back to dashboard</a></header>
<div class="meta"><span>{st.st_size:,} bytes</span><span>sha256 <code>{hashlib.sha256(data).hexdigest()}</code></span>
<span>modified {datetime.fromtimestamp(st.st_mtime):%Y-%m-%d %H:%M}</span><span>read-only copy, regenerated on each dashboard build</span></div>
<p></p><div class="panel">{body}</div></div></body></html>"""
        (out_dir / viewer_name(rel)).write_text(page)
