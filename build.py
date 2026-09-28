#!/usr/bin/env python3
"""Build a static Stremio addon from the iptv-org Israel playlist.

Downloads the M3U, parses it, and writes every addon endpoint as a plain
JSON file under ./dist, ready to be served by GitHub Pages.

Usage: python3 build.py [--playlist URL_OR_FILE] [--out DIR] [--base-url URL]
"""
import argparse
import html
import json
import re
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/il.m3u"
ASSETS_DIR = Path(__file__).parent / "assets"
ID_PREFIX = "iltv_"
CATALOG_ID = "iltv"

MANIFEST = {
    "id": "community.iptv.israel",
    "version": "1.0.0",
    "name": "Israeli TV",
    "description": "Live Israeli TV channels from the public iptv-org playlist. Updated automatically.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["tv"],
    "idPrefixes": [ID_PREFIX],
    "behaviorHints": {"configurable": False},
}

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
QUALITY_RE = re.compile(r"\s*\((\d+p)\)")
TAG_RE = re.compile(r"\s*\[([^\]]*)\]")


def fetch(source):
    if re.match(r"https?://", source):
        req = urllib.request.Request(source, headers={"User-Agent": "stremio-il-builder"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read().decode("utf-8", "replace")
    return Path(source).read_text(encoding="utf-8")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "", text.lower()) or "channel"


def parse_m3u(text):
    """Yield one dict per playlist entry."""
    entry = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#EXTINF"):
            attrs = dict(ATTR_RE.findall(line))
            # Attribute values may contain commas (user agents), so strip
            # them before taking the display name after the first comma.
            rest = ATTR_RE.sub("", line)
            title = rest.split(",", 1)[1].strip() if "," in rest else attrs.get("tvg-name", "")
            entry = {"attrs": attrs, "title": title, "headers": {}}
            if attrs.get("http-user-agent"):
                entry["headers"]["User-Agent"] = attrs["http-user-agent"]
            if attrs.get("http-referrer"):
                entry["headers"]["Referer"] = attrs["http-referrer"]
        elif line.startswith("#EXTVLCOPT:") and entry is not None:
            key, _, value = line[len("#EXTVLCOPT:"):].partition("=")
            if key == "http-user-agent":
                entry["headers"]["User-Agent"] = value
            elif key == "http-referrer":
                entry["headers"]["Referer"] = value
        elif not line.startswith("#") and entry is not None:
            entry["url"] = line
            yield entry
            entry = None


def build_channels(entries):
    """Group playlist entries into channels (one channel may have several streams)."""
    channels = {}
    for e in entries:
        attrs, title = e["attrs"], e["title"]
        quality = QUALITY_RE.search(title)
        tags = TAG_RE.findall(title)
        name = TAG_RE.sub("", QUALITY_RE.sub("", title)).strip()
        name = re.sub(r"\s*\(Israel\)", "", name)

        tvg_id = attrs.get("tvg-id", "").split("@")[0]
        cid = ID_PREFIX + slugify(tvg_id or name)
        genres = [g.strip() for g in attrs.get("group-title", "").split(";") if g.strip()]
        genres = ["Other" if g == "Undefined" else g for g in genres] or ["Other"]

        ch = channels.setdefault(cid, {
            "id": cid,
            "name": name,
            "logo": attrs.get("tvg-logo") or None,
            "genres": [],
            "streams": [],
        })
        for g in genres:
            if g not in ch["genres"]:
                ch["genres"].append(g)
        ch["streams"].append({
            "url": e["url"],
            "quality": quality.group(1) if quality else None,
            "tags": tags,
            "headers": e["headers"],
        })
    return sorted(channels.values(), key=lambda c: c["name"].lower())


def meta_preview(ch):
    return {
        "id": ch["id"],
        "type": "tv",
        "name": ch["name"],
        "poster": ch["logo"],
        "posterShape": "square",
        "logo": ch["logo"],
        "genres": ch["genres"],
    }


def meta_full(ch):
    meta = meta_preview(ch)
    meta["background"] = ch["logo"]
    meta["description"] = f"{ch['name']} — live. Genres: {', '.join(ch['genres'])}."
    return meta


def stremio_stream(s, idx, total):
    label = "Live"
    if total > 1:
        label += f" #{idx + 1}"
    details = [x for x in [s["quality"], *s["tags"]] if x]
    stream = {
        "url": s["url"],
        "name": "Israeli TV",
        "title": " · ".join([label, *details]),
    }
    hints = {}
    # Plain-http streams and streams needing custom headers can't play
    # directly in a browser; notWebReady routes them through Stremio's
    # local streaming server, which is also what applies proxyHeaders.
    if s["url"].startswith("http://") or s["headers"]:
        hints["notWebReady"] = True
    if s["headers"]:
        hints["proxyHeaders"] = {"request": s["headers"]}
    if hints:
        stream["behaviorHints"] = hints
    return stream


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_index(out, base_url, count, genres):
    manifest_url = f"{base_url.rstrip('/')}/manifest.json" if base_url else "manifest.json"
    app_url = re.sub(r"^https?://", "stremio://", manifest_url) if base_url else "#"
    web_url = "https://web.stremio.com/#/addons?addon=" + urllib.parse.quote(manifest_url, safe="")
    e = html.escape
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Israeli TV · Stremio addon</title>
<link rel="icon" href="logo.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="logo.png">
<meta property="og:title" content="Israeli TV for Stremio">
<meta property="og:description" content="{count} live Israeli TV channels in Stremio. Free, no account needed.">
<meta property="og:image" content="logo.png">
<style>
:root{{--bg:#f5f7fb;--card:#fff;--fg:#141824;--muted:#5b6475;--accent:#2457d6;--code:#eef1f7;--border:#dfe4ee}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0e1117;--card:#161a23;--fg:#e8ebf2;--muted:#9aa3b5;--accent:#5b8cff;--code:#1f2430;--border:#262c3a}}}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--fg);line-height:1.55}}
main{{max-width:620px;margin:0 auto;padding:48px 16px}}
header{{display:flex;gap:18px;align-items:center;margin-bottom:28px}}
header img{{width:84px;height:84px;border-radius:20px}}
h1{{margin:0;font-size:1.8rem}}
header p{{margin:4px 0 0;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:14px;padding:20px;margin-bottom:18px}}
h2{{margin:0 0 10px;font-size:1.1rem}}
.btns{{display:flex;flex-wrap:wrap;gap:10px}}
.btn{{display:inline-block;background:var(--accent);color:#fff;padding:11px 18px;border-radius:9px;text-decoration:none;font-weight:600}}
.btn.alt{{background:transparent;color:var(--accent);border:1.5px solid var(--accent)}}
.url{{display:flex;gap:8px;margin-top:8px}}
.url code{{flex:1;background:var(--code);padding:9px 11px;border-radius:8px;font-size:.85rem;overflow-x:auto;white-space:nowrap}}
.url button{{border:1px solid var(--border);background:var(--card);color:var(--fg);border-radius:8px;padding:0 14px;cursor:pointer;font:inherit}}
ol{{margin:0;padding-left:20px}} li{{margin:4px 0}}
.tags{{display:flex;flex-wrap:wrap;gap:6px}}
.tags span{{background:var(--code);border-radius:99px;padding:3px 10px;font-size:.85rem}}
.muted{{color:var(--muted);font-size:.9rem}}
a{{color:var(--accent)}}
</style></head><body><main>
<header><img src="logo.png" alt=""><div><h1>Israeli TV for Stremio</h1>
<p>{count} live channels · updated every 6 hours · free</p></div></header>

<section class="card"><h2>Install</h2>
<div class="btns"><a class="btn" href="{e(app_url)}">Open in Stremio app</a>
<a class="btn alt" href="{e(web_url)}">Install via Stremio Web</a></div>
<p class="muted" style="margin:14px 0 0">Or paste this URL into the search box on Stremio's Addons page:</p>
<div class="url"><code id="u">{e(manifest_url)}</code><button onclick="navigator.clipboard.writeText(document.getElementById('u').textContent);this.textContent='Copied'">Copy</button></div>
</section>

<section class="card"><h2>How to watch</h2><ol>
<li>Install the addon using one of the options above.</li>
<li>In Stremio go to <b>Discover → TV → Israeli TV</b>.</li>
<li>Pick a genre (optional), choose a channel and press play.</li>
</ol></section>

<section class="card"><h2>Genres</h2><div class="tags">{"".join(f"<span>{e(g)}</span>" for g in genres)}</div></section>

<section class="card"><h2>Good to know</h2><ul class="muted" style="margin:0;padding-left:20px">
<li>Use the Stremio <b>desktop, Android or TV</b> app. Most streams don't play on web.stremio.com.</li>
<li>Many channels are geo-restricted and only play from Israel.</li>
<li>Streams come from the public <a href="https://github.com/iptv-org/iptv">iptv-org</a> playlist; some may be offline at times.</li>
</ul></section>
<p class="muted">Source code: <a href="https://github.com/Mudales/stremio-tv-il">github.com/Mudales/stremio-tv-il</a></p>
</main></body></html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--playlist", default=PLAYLIST_URL)
    ap.add_argument("--out", default="dist")
    ap.add_argument("--base-url", default="", help="Public URL of the site, used on the install page")
    args = ap.parse_args()

    channels = build_channels(parse_m3u(fetch(args.playlist)))
    if not channels:
        raise SystemExit("Playlist parsed to zero channels; refusing to publish an empty addon.")

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    genres = sorted({g for ch in channels for g in ch["genres"]})
    for f in ASSETS_DIR.glob("*"):
        shutil.copy(f, out / f.name)

    manifest = dict(MANIFEST)
    manifest["logo"] = f"{args.base_url.rstrip('/')}/logo.png" if args.base_url else "logo.png"
    manifest["catalogs"] = [{
        "type": "tv",
        "id": CATALOG_ID,
        "name": "Israeli TV",
        "extra": [{"name": "genre", "options": genres, "isRequired": False}],
    }]
    write_json(out / "manifest.json", manifest)

    write_json(out / "catalog" / "tv" / f"{CATALOG_ID}.json",
               {"metas": [meta_preview(c) for c in channels]})
    for g in genres:
        write_json(out / "catalog" / "tv" / CATALOG_ID / f"genre={g}.json",
                   {"metas": [meta_preview(c) for c in channels if g in c["genres"]]})

    for ch in channels:
        write_json(out / "meta" / "tv" / f"{ch['id']}.json", {"meta": meta_full(ch)})
        total = len(ch["streams"])
        write_json(out / "stream" / "tv" / f"{ch['id']}.json",
                   {"streams": [stremio_stream(s, i, total) for i, s in enumerate(ch["streams"])]})

    (out / ".nojekyll").write_text("")
    write_index(out, args.base_url, len(channels), genres)
    print(f"Built {len(channels)} channels, {sum(len(c['streams']) for c in channels)} streams, "
          f"{len(genres)} genres -> {out}/")


if __name__ == "__main__":
    main()
