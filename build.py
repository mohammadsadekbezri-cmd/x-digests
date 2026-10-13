#!/usr/bin/env python3
"""Render digests/*.md into a single self-contained site/index.html."""
import html, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIGESTS, SITE = ROOT / "digests", ROOT / "site"
TYPES = {"tech-ai": "Tech & AI", "startups": "Startups & Launches", "general": "General"}

try:
    import markdown
    def md(text): return markdown.markdown(text, extensions=["extra", "sane_lists"])
except ImportError:
    def md(text):
        t = html.escape(text)
        t = re.sub(r"&lt;(https?://[^&\s]+)&gt;", r'<a href="\1">\1</a>', t)
        return "<pre>" + t + "</pre>"

def parse(path):
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1); meta[k.strip()] = v.strip()
        body = m.group(2)
    stem = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", path.stem)
    meta.setdefault("date", stem.group(1) if stem else "")
    meta.setdefault("type", stem.group(2) if stem else "general")
    meta.setdefault("title", path.stem)
    body = re.sub(r"(?m)^ {2,3}([-*] )", r"    \1", body)  # nested lists need 4 spaces
    h = md(body)
    h = re.sub(r'<a href=', '<a target="_blank" rel="noopener noreferrer" href=', h)
    return {"id": path.stem, "title": meta["title"], "date": meta["date"], "type": meta["type"],
            "label": TYPES.get(meta["type"], meta["type"]), "html": h,
            "text": re.sub(r"<[^>]+>", " ", h).lower()}

CSS = """
:root{--bg:#0f1115;--panel:#171a21;--fg:#e6e8ee;--muted:#9aa3b2;--acc:#5b9dff;--bd:#262b36;--chip:#222838}
[data-theme=light]{--bg:#f6f7fb;--panel:#fff;--fg:#1b1f29;--muted:#5d6676;--acc:#1f6feb;--bd:#e2e5ec;--chip:#eef1f7}
*{box-sizing:border-box}body{margin:0;font:15px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
header{position:sticky;top:0;z-index:5;background:var(--panel);border-bottom:1px solid var(--bd);padding:12px 20px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
header h1{font-size:18px;margin:0 12px 0 0}
input[type=search]{flex:1;min-width:180px;padding:8px 12px;border-radius:8px;border:1px solid var(--bd);background:var(--bg);color:var(--fg)}
button{cursor:pointer;border:1px solid var(--bd);background:var(--chip);color:var(--fg);padding:6px 12px;border-radius:999px;font-size:13px}
button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.wrap{display:grid;grid-template-columns:230px 1fr;gap:20px;max-width:1200px;margin:0 auto;padding:20px}
aside{position:sticky;top:76px;align-self:start;max-height:calc(100vh - 96px);overflow:auto}
aside h3{font-size:12px;text-transform:uppercase;color:var(--muted);margin:14px 0 6px}
aside a{display:block;color:var(--fg);text-decoration:none;padding:4px 8px;border-radius:6px;font-size:13px}
aside a:hover{background:var(--chip)}
article{background:var(--panel);border:1px solid var(--bd);border-radius:12px;padding:18px 24px;margin-bottom:20px}
article h2.t{margin:0 0 4px;font-size:20px}.meta{color:var(--muted);font-size:13px;margin-bottom:8px}
.tag{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 10px;margin-left:6px;font-size:12px}
article a{color:var(--acc);word-break:break-word}article h2{font-size:17px;border-top:1px solid var(--bd);padding-top:12px}
mark{background:#ffd54a;color:#000}.empty{color:var(--muted);text-align:center;padding:40px}
@media(max-width:800px){.wrap{grid-template-columns:1fr}aside{position:static;max-height:none}}
"""

JS = """
const D=window.DIGESTS;let type='all',q='';
const $=s=>document.querySelector(s);
function render(){
 const list=D.filter(d=>(type==='all'||d.type===type)&&(!q||d.text.includes(q)||d.title.toLowerCase().includes(q)));
 $('#main').innerHTML=list.length?list.map(d=>`<article id="${d.id}"><h2 class="t">${d.title}</h2><div class="meta">${d.date}<span class="tag">${d.label}</span></div>${d.html}</article>`).join(''):'<div class="empty">No digests match.</div>';
 const by={};list.forEach(d=>(by[d.date]=by[d.date]||[]).push(d));
 $('#side').innerHTML=Object.keys(by).sort().reverse().map(k=>`<h3>${k}</h3>`+by[k].map(d=>`<a href="#${d.id}">${d.label}</a>`).join('')).join('');
 if(q){document.querySelectorAll('#main article').forEach(a=>{const w=document.createTreeWalker(a,NodeFilter.SHOW_TEXT);const ns=[];while(w.nextNode())ns.push(w.currentNode);
  ns.forEach(n=>{const i=n.data.toLowerCase().indexOf(q);if(i<0)return;const r=document.createRange();r.setStart(n,i);r.setEnd(n,i+q.length);const m=document.createElement('mark');r.surroundContents(m);});});}
}
document.querySelectorAll('[data-type]').forEach(b=>b.onclick=()=>{type=b.dataset.type;document.querySelectorAll('[data-type]').forEach(x=>x.classList.toggle('on',x===b));render();});
$('#q').oninput=e=>{q=e.target.value.trim().toLowerCase();render();};
const th=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark');
document.documentElement.dataset.theme=th;
$('#theme').onclick=()=>{const t=document.documentElement.dataset.theme==='light'?'dark':'light';document.documentElement.dataset.theme=t;localStorage.setItem('theme',t);};
render();
"""

def build():
    docs = [parse(p) for p in DIGESTS.glob("*.md")]
    order = {"general": 0, "tech-ai": 1, "startups": 2}
    docs.sort(key=lambda d: (d["date"], -order.get(d["type"], 9)), reverse=True)
    btns = '<button class="on" data-type="all">All</button>' + "".join(
        f'<button data-type="{k}">{html.escape(v)}</button>' for k, v in TYPES.items())
    data = json.dumps(docs).replace("</", "<\\/")
    page = f"""<!DOCTYPE html>
<html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>X Digests</title><style>{CSS}</style></head>
<body><header><h1>📡 X Digests</h1>{btns}<input id="q" type="search" placeholder="Search digests…">
<button id="theme" title="Toggle theme">◐</button></header>
<div class="wrap"><aside><h3>Archive</h3><nav id="side"></nav></aside><main id="main"></main></div>
<script>window.DIGESTS={data};</script><script>{JS}</script></body></html>"""
    SITE.mkdir(exist_ok=True)
    (SITE / "index.html").write_text(page, encoding="utf-8")
    print(f"Built {SITE/'index.html'} with {len(docs)} digest(s)")

if __name__ == "__main__":
    build()
