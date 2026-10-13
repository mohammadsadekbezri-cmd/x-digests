#!/usr/bin/env python3
"""Render digests/*.md into a visual static site.
Writes site/index.html (assets via ../assets/) and index.html at repo root (assets/ paths).
Tweet data from the public syndication endpoint and article og: data are cached in cache/;
images are downloaded to assets/. Nothing is invented: on fetch failure a plain link card is shown."""
import hashlib, html, json, re, sys, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIGESTS, SITE, CACHE, ASSETS = ROOT/"digests", ROOT/"site", ROOT/"cache", ROOT/"assets"
TYPES = {"tech-ai": "Tech & AI", "startups": "Startups & Launches", "general": "General"}
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
TWEET_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")
URL_RE = re.compile(r"<(https?://[^>\s]+)>|\((https?://[^)\s]+)\)|(?<![(<\"])(https?://[^\s<>)\"]+)")
STATS = {"tweet_ok": 0, "tweet_fail": 0, "og_img": 0, "og_noimg": 0}

try:
    import markdown
    def md(t): return markdown.markdown(t, extensions=["extra", "sane_lists"])
except ImportError:
    def md(t): return "<p>" + html.escape(t) + "</p>"

def esc(s): return html.escape(str(s or ""), quote=True)

def get(url, timeout=15, limit=6_000_000):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit), r.headers.get_content_type()

def download(url, name):
    """Download an image into assets/, return relative file name or None."""
    if not url: return None
    for p in ASSETS.glob(name + ".*"):
        return p.name
    try:
        data, ctype = get(url)
        if not ctype.startswith("image/") or len(data) < 200: return None
        ext = {"image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(ctype, "jpg")
        ASSETS.mkdir(exist_ok=True); (ASSETS/f"{name}.{ext}").write_bytes(data)
        return f"{name}.{ext}"
    except Exception:
        return None

# ---------- tweets ----------
def tweet_data(tid):
    c = CACHE/f"{tid}.json"
    if c.exists(): return json.loads(c.read_text())
    try:
        raw, _ = get(f"https://cdn.syndication.twimg.com/tweet-result?id={tid}&token=a")
        d = json.loads(raw)
        if not d.get("user"): return None
        CACHE.mkdir(exist_ok=True); c.write_text(json.dumps(d))
        return d
    except Exception:
        return None

def first_media(d):
    for t in (d, d.get("quoted_tweet") or {}):
        for m in t.get("mediaDetails") or []:
            if m.get("media_url_https"): return m["media_url_https"]
        for p in t.get("photos") or []:
            if p.get("url"): return p["url"]
        if (t.get("video") or {}).get("poster"): return t["video"]["poster"]
    return None

def tweet_info(tid):
    d = tweet_data(tid)
    if not d: return None
    u = d["user"]
    text = d.get("text", "")
    a, b = (d.get("display_text_range") or [0, len(text)])[:2]
    text = re.sub(r"\s*https://t\.co/\w+\s*$", "", text[a:b] if b else text)
    av = download(u.get("profile_image_url_https", "").replace("_normal", "_bigger"), f"av-{u.get('screen_name','x')}")
    media = download(first_media(d), f"tw-{tid}")
    return {"id": tid, "name": u.get("name"), "handle": u.get("screen_name"), "text": text,
            "avatar": av, "media": media, "likes": d.get("favorite_count"),
            "replies": d.get("conversation_count"), "date": (d.get("created_at") or "")[:10]}

# ---------- link previews ----------
def og_info(url):
    h = hashlib.sha1(url.encode()).hexdigest()[:12]
    c = CACHE/f"og-{h}.json"
    if c.exists(): info = json.loads(c.read_text())
    else:
        info = {"url": url}
        try:
            raw, ctype = get(url, limit=800_000)
            page = raw.decode("utf-8", "ignore")
            def meta(*keys):
                for k in keys:
                    m = re.search(r'<meta[^>]+(?:property|name)=["\']%s["\'][^>]*content=["\']([^"\']+)' % re.escape(k), page, re.I) \
                        or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]*(?:property|name)=["\']%s["\']' % re.escape(k), page, re.I)
                    if m: return html.unescape(m.group(1)).strip()
            t = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
            info.update(title=meta("og:title", "twitter:title") or (html.unescape(t.group(1)).strip() if t else None),
                        image=meta("og:image", "twitter:image", "og:image:url"), site=meta("og:site_name"))
            if info.get("image"): info["image"] = urllib.parse.urljoin(url, info["image"])
            CACHE.mkdir(exist_ok=True); c.write_text(json.dumps(info))
        except Exception:
            pass  # not cached: retried on next build
    info["local"] = download(info.get("image"), f"og-{h}") if info.get("image") else None
    return info

# ---------- digest parsing ----------
def parse(path):
    raw = path.read_text(encoding="utf-8")
    meta, body = {}, raw
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", raw, re.S)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line: k, v = line.split(":", 1); meta[k.strip()] = v.strip()
        body = m.group(2)
    stem = re.match(r"(\d{4}-\d{2}-\d{2})-(.+)", path.stem)
    meta.setdefault("date", stem.group(1) if stem else ""); meta.setdefault("type", stem.group(2) if stem else "general")
    meta.setdefault("title", path.stem)
    sections, intro, cur, item = [], [], None, None
    for line in body.splitlines():
        if line.startswith("## "):
            cur = {"title": line[3:].strip(), "items": []}; sections.append(cur); item = None
        elif re.match(r"^(\d+\.|[-*]) ", line):
            if cur is None: cur = {"title": "", "items": []}; sections.append(cur)
            num = re.match(r"^(\d+)\.", line)
            item = {"num": num.group(1) if num else "", "lines": [re.sub(r"^(\d+\.|[-*]) ", "", line)]}
            cur["items"].append(item)
        elif line.strip() and item and line[:1].isspace():
            item["lines"].append(re.sub(r"^ {2,4}", "", line))
        elif line.strip():
            (intro if cur is None else item["lines"] if item else intro).append(line.strip())
    return {"id": path.stem, "title": meta["title"], "date": meta["date"], "type": meta["type"],
            "label": TYPES.get(meta["type"], meta["type"]), "intro": " ".join(intro), "sections": sections}

def urls_in(text):
    out = []
    for m in URL_RE.finditer(text):
        u = (m.group(1) or m.group(2) or m.group(3)).rstrip(".,;")
        if u not in out: out.append(u)
    return out

def links_newtab(h): return h.replace("<a href=", '<a target="_blank" rel="noopener noreferrer" href=')

def tweet_card(url, t, A):
    tid = TWEET_RE.search(url).group(2)
    if not t:
        return f'<a class="plain" target="_blank" rel="noopener" href="{esc(url)}">𝕏 View post · {esc(url.split("//")[1])}</a>'
    stats = " · ".join(x for x in [f"♥ {t['likes']:,}" if t.get("likes") is not None else "",
                                     f"💬 {t['replies']:,}" if t.get("replies") else "", t.get("date", "")] if x)
    av = f'<img class="av" loading="lazy" src="{A}{t["avatar"]}" alt="">' if t.get("avatar") else '<span class="av"></span>'
    media = f'<img class="tmedia" loading="lazy" src="{A}{t["media"]}" alt="">' if t.get("media") else ""
    return (f'<div class="tw" data-id="{tid}"><blockquote class="twitter-tweet" data-dnt="true">'
            f'<div class="tcard"><div class="thead">{av}<div><b>{esc(t["name"])}</b><br><span class="mut">@{esc(t["handle"])}</span></div>'
            f'<span class="xlogo">𝕏</span></div><p class="ttext">{esc(t["text"])}</p>{media}'
            f'<div class="mut tstat">{stats} · <a href="https://twitter.com/{esc(t["handle"])}/status/{tid}" target="_blank" rel="noopener">View on X</a></div>'
            f'</div></blockquote></div>')

def link_card(o, A):
    host = urllib.parse.urlparse(o["url"]).netloc.replace("www.", "")
    img = f'<img loading="lazy" src="{A}{o["local"]}" alt="">' if o.get("local") else f'<div class="noimg">{esc(host[:1].upper())}</div>'
    return (f'<a class="lcard" target="_blank" rel="noopener noreferrer" href="{esc(o["url"])}">{img}'
            f'<div><b>{esc(o.get("title") or host)}</b><span class="mut">{esc(o.get("site") or host)}</span></div></a>')

def build():
    docs = [parse(p) for p in DIGESTS.glob("*.md")]
    order = {"general": 0, "tech-ai": 1, "startups": 2}
    docs.sort(key=lambda d: (d["date"], -order.get(d["type"], 9)), reverse=True)
    allurls = {u for d in docs for s in d["sections"] for it in s["items"] for u in urls_in("\n".join(it["lines"]))}
    tids = {TWEET_RE.search(u).group(2) for u in allurls if TWEET_RE.search(u)}
    others = [u for u in allurls if not TWEET_RE.search(u)]
    with ThreadPoolExecutor(8) as ex:
        tweets = dict(zip(tids, ex.map(tweet_info, tids)))
        ogs = dict(zip(others, ex.map(og_info, others)))
    STATS["tweet_ok"] = sum(1 for v in tweets.values() if v); STATS["tweet_fail"] = len(tweets) - STATS["tweet_ok"]
    STATS["og_img"] = sum(1 for v in ogs.values() if v.get("local")); STATS["og_noimg"] = len(ogs) - STATS["og_img"]
    for prefix, out in (("../assets/", SITE/"index.html"), ("assets/", ROOT/"index.html")):
        out.parent.mkdir(exist_ok=True)
        out.write_text(render(docs, tweets, ogs, prefix), encoding="utf-8")
        print("Built", out)
    print(f"Tweets: {STATS['tweet_ok']} rich fallback data / {STATS['tweet_fail']} plain link; "
          f"links: {STATS['og_img']} with image / {STATS['og_noimg']} without")

def render(docs, tweets, ogs, A):
    parts, hero = [], []
    for di, d in enumerate(docs):
        secs = []
        for s in d["sections"]:
            cards = []
            for it in s["items"]:
                text = "\n".join(it["lines"])
                urls = urls_in(text)
                # strip bare URL-only sub-bullets from the text; they become cards
                shown = "\n".join(l for l in it["lines"] if not re.fullmatch(r"\s*-\s*<https?://[^>]+>\s*", l))
                body = links_newtab(md(shown))
                embeds = []
                for u in urls[:4]:
                    if TWEET_RE.search(u): embeds.append(tweet_card(u, tweets.get(TWEET_RE.search(u).group(2)), A))
                    elif "news.ycombinator.com" not in u or u not in [e for e in urls[:0]]:
                        embeds.append(link_card(ogs.get(u, {"url": u}), A))
                more = "".join(f'<a class="plain" target="_blank" rel="noopener" href="{esc(u)}">{esc(u)}</a>' for u in urls[4:])
                search = re.sub(r"<[^>]+>", " ", body).lower() + " " + " ".join(
                    (tweets.get(TWEET_RE.search(u).group(2)) or {}).get("text", "").lower() for u in urls if TWEET_RE.search(u))
                num = f'<span class="num">{esc(it["num"])}</span>' if it["num"] else ""
                cards.append(f'<div class="item" data-s="{esc(search)}">{num}<div class="ibody">{body}</div>'
                             f'<div class="embeds">{"".join(embeds)}{more}</div></div>')
                if di == 0 and len(hero) < 4:
                    img = None
                    for u in urls:
                        m = TWEET_RE.search(u)
                        t = tweets.get(m.group(2)) if m else None
                        img = (t or {}).get("media") if m else ogs.get(u, {}).get("local")
                        if img: break
                    if img:
                        title = re.sub(r"<[^>]+>", "", re.search(r"<strong>(.*?)</strong>", body).group(1)) if "<strong>" in body else re.sub(r"<[^>]+>", "", body)[:90]
                        hero.append(f'<a class="hcard" href="#{d["id"]}"><img src="{A}{img}" alt=""><span class="badge b-{d["type"]}">{esc(d["label"])}</span><b>{esc(title)}</b></a>')
            secs.append((f'<h3 class="sec">{esc(s["title"])}</h3>' if s["title"] else "") + f'<div class="grid">{"".join(cards)}</div>')
        parts.append(f'<section class="digest" id="{d["id"]}" data-type="{esc(d["type"])}">'
                     f'<div class="dhead"><span class="badge b-{d["type"]}">{esc(d["label"])}</span><span class="mut">{esc(d["date"])}</span>'
                     f'<h2>{esc(d["title"])}</h2>{f"<p class=mut>{esc(d[chr(105)+chr(110)+chr(116)+chr(114)+chr(111)])}</p>" if d["intro"] else ""}</div>{"".join(secs)}</section>')
    side, by = [], {}
    for d in docs: by.setdefault(d["date"], []).append(d)
    for k in sorted(by, reverse=True):
        side.append(f"<h4>{esc(k)}</h4>" + "".join(f'<a href="#{d["id"]}" data-type="{d["type"]}"><span class="dot b-{d["type"]}"></span>{esc(d["label"])}</a>' for d in by[k]))
    btns = '<button class="on" data-f="all">All</button>' + "".join(f'<button data-f="{k}">{esc(v)}</button>' for k, v in TYPES.items())
    heroh = f'<div class="hero"><h3 class="sec">Top stories · {esc(docs[0]["date"])}</h3><div class="hgrid">{"".join(hero)}</div></div>' if hero else ""
    return PAGE.replace("{{BTNS}}", btns).replace("{{SIDE}}", "".join(side)).replace("{{HERO}}", heroh).replace("{{MAIN}}", "".join(parts))

PAGE = r"""<!DOCTYPE html><html lang="en" data-theme="dark"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>X Digests</title>
<script>document.documentElement.dataset.theme=localStorage.getItem('theme')||(matchMedia('(prefers-color-scheme: light)').matches?'light':'dark')</script>
<style>
:root{--bg:#0b0d12;--panel:#151922;--panel2:#1c2130;--fg:#e8ebf2;--mut:#98a2b3;--acc:#5b9dff;--bd:#252b39;--sh:0 4px 18px rgba(0,0,0,.35)}
[data-theme=light]{--bg:#f3f5f9;--panel:#fff;--panel2:#f6f8fc;--fg:#161a23;--mut:#5b6474;--acc:#1f6feb;--bd:#e1e5ee;--sh:0 4px 16px rgba(20,30,60,.08)}
*{box-sizing:border-box}body{margin:0;font:15px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:var(--bg);color:var(--fg)}
a{color:var(--acc)}.mut{color:var(--mut);font-size:13px}
header{position:sticky;top:0;z-index:20;background:color-mix(in srgb,var(--panel) 88%,transparent);backdrop-filter:blur(10px);border-bottom:1px solid var(--bd);padding:12px 22px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
header h1{font-size:19px;margin:0 14px 0 0;letter-spacing:-.3px}
input[type=search]{flex:1;min-width:180px;padding:9px 14px;border-radius:10px;border:1px solid var(--bd);background:var(--bg);color:var(--fg)}
button{cursor:pointer;border:1px solid var(--bd);background:var(--panel2);color:var(--fg);padding:7px 14px;border-radius:999px;font-size:13px}
button.on{background:var(--acc);color:#fff;border-color:var(--acc)}
.wrap{display:grid;grid-template-columns:210px 1fr;gap:26px;max-width:1440px;margin:0 auto;padding:22px}
aside{position:sticky;top:80px;align-self:start;max-height:calc(100vh - 100px);overflow:auto}
aside h4{font-size:12px;color:var(--mut);margin:16px 0 6px;text-transform:uppercase;letter-spacing:.5px}
aside a{display:flex;gap:8px;align-items:center;color:var(--fg);text-decoration:none;padding:6px 8px;border-radius:8px;font-size:14px}aside a:hover{background:var(--panel2)}
.dot{width:8px;height:8px;border-radius:50%}
.badge{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:600;color:#fff;margin-right:8px}
.b-tech-ai{background:#6d5dfc}.b-startups{background:#e8590c}.b-general{background:#0ca678}
.hero{margin-bottom:28px}.hgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:16px}
.hcard{position:relative;display:block;border-radius:14px;overflow:hidden;aspect-ratio:16/10;box-shadow:var(--sh);color:#fff;text-decoration:none;background:#222}
.hcard img{width:100%;height:100%;object-fit:cover;transition:transform .3s}.hcard:hover img{transform:scale(1.04)}
.hcard:after{content:"";position:absolute;inset:0;background:linear-gradient(transparent 35%,rgba(0,0,0,.85))}
.hcard .badge{position:absolute;top:10px;left:10px;z-index:1}.hcard b{position:absolute;left:12px;right:12px;bottom:10px;z-index:1;font-size:15px;line-height:1.3}
.digest{margin-bottom:40px}.dhead h2{margin:6px 0 4px;font-size:24px;letter-spacing:-.4px}
h3.sec{font-size:13px;text-transform:uppercase;letter-spacing:.8px;color:var(--mut);margin:26px 0 12px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;align-items:start}
.item{position:relative;background:var(--panel);border:1px solid var(--bd);border-radius:14px;padding:16px 16px 14px;box-shadow:var(--sh)}
.num{position:absolute;top:-10px;left:-8px;background:var(--acc);color:#fff;font-weight:700;font-size:12px;border-radius:999px;min-width:24px;height:24px;display:grid;place-items:center;padding:0 6px}
.ibody p{margin:0 0 8px}.ibody ul{margin:4px 0;padding-left:18px}.ibody a{word-break:break-all}
.embeds{display:flex;flex-direction:column;gap:10px;margin-top:10px}
.tw blockquote{margin:0}.tw iframe{max-width:100%!important}.twitter-tweet-rendered{margin:0!important}
.tcard{border:1px solid var(--bd);background:var(--panel2);border-radius:12px;padding:12px}
.thead{display:flex;gap:10px;align-items:center;line-height:1.25}.thead b{font-size:14px}
.av{width:40px;height:40px;border-radius:50%;background:var(--bd);flex:none}.xlogo{margin-left:auto;font-size:18px;opacity:.7}
.ttext{white-space:pre-wrap;margin:10px 0;font-size:14px}.tmedia{width:100%;max-height:320px;object-fit:cover;border-radius:10px;border:1px solid var(--bd)}
.tstat{margin-top:8px}
.lcard{display:flex;gap:12px;align-items:center;border:1px solid var(--bd);background:var(--panel2);border-radius:12px;overflow:hidden;text-decoration:none;color:var(--fg)}
.lcard img,.lcard .noimg{width:110px;height:74px;object-fit:cover;flex:none}.lcard .noimg{display:grid;place-items:center;font-size:28px;font-weight:700;color:var(--mut);background:var(--bd)}
.lcard div{display:flex;flex-direction:column;padding:6px 10px 6px 0;font-size:13px;line-height:1.35}.lcard b{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.plain{display:block;font-size:13px;border:1px dashed var(--bd);border-radius:10px;padding:8px 10px;word-break:break-all;text-decoration:none}
.hide{display:none!important}.empty{color:var(--mut);text-align:center;padding:40px}
@media(max-width:820px){.wrap{grid-template-columns:1fr;padding:14px}aside{position:static;max-height:none}.grid{grid-template-columns:1fr}}
</style></head><body>
<header><h1>📡 X Digests</h1>{{BTNS}}<input id="q" type="search" placeholder="Search items and tweets…"><button id="theme" title="Toggle dark/light">◐</button></header>
<div class="wrap"><aside><h4>Archive</h4>{{SIDE}}</aside><main>{{HERO}}{{MAIN}}<div class="empty hide" id="none">No items match.</div></main></div>
<script>
const $=s=>document.querySelector(s),$$=s=>[...document.querySelectorAll(s)];let f='all',q='';
function apply(){let any=0;$$('.digest').forEach(d=>{let n=0;d.querySelectorAll('.item').forEach(i=>{const ok=!q||i.dataset.s.includes(q);i.classList.toggle('hide',!ok);n+=ok});
 d.querySelectorAll('.grid').forEach(g=>{const v=[...g.children].some(c=>!c.classList.contains('hide'));g.classList.toggle('hide',!v);if(g.previousElementSibling&&g.previousElementSibling.tagName=='H3')g.previousElementSibling.classList.toggle('hide',!v)});
 const show=(f=='all'||d.dataset.type==f)&&n>0;d.classList.toggle('hide',!show);any|=show});
 $$('aside a').forEach(a=>a.classList.toggle('hide',f!='all'&&a.dataset.type!=f));$('.hero')&&$('.hero').classList.toggle('hide',!!q||f!='all');$('#none').classList.toggle('hide',!!any)}
$$('[data-f]').forEach(b=>b.onclick=()=>{f=b.dataset.f;$$('[data-f]').forEach(x=>x.classList.toggle('on',x==b));apply()});
$('#q').oninput=e=>{q=e.target.value.trim().toLowerCase();apply()};
// Official X embeds: static fallback lives inside <blockquote class="twitter-tweet">; widgets.js upgrades it lazily.
const orig=new Map();$$('.tw').forEach(t=>orig.set(t,t.innerHTML));
let wjs=null;function loadW(){if(!wjs){wjs=new Promise(r=>{const s=document.createElement('script');s.src='https://platform.twitter.com/widgets.js';s.async=1;s.onload=()=>r(window.twttr);s.onerror=()=>r(null);document.head.appendChild(s)})}return wjs}
function embed(t){if(t.dataset.done)return;t.dataset.done=1;t.querySelector('blockquote').dataset.theme=document.documentElement.dataset.theme;loadW().then(tw=>{tw&&tw.widgets&&tw.widgets.load(t)})}
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting){io.unobserve(e.target);embed(e.target)}}),{rootMargin:'400px'});
const observeAll=()=>$$('.tw').forEach(t=>io.observe(t));if(location.protocol!='file:'||navigator.onLine)observeAll();
$('#theme').onclick=()=>{const th=document.documentElement.dataset.theme=='light'?'dark':'light';document.documentElement.dataset.theme=th;localStorage.setItem('theme',th);
 $$('.tw').forEach(t=>{if(t.dataset.done){t.innerHTML=orig.get(t);delete t.dataset.done}});observeAll()};
apply();
</script></body></html>"""

if __name__ == "__main__":
    build()
