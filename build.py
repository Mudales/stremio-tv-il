#!/usr/bin/env python3
"""Build a static Stremio addon for Israeli TV from several public playlists.

Downloads every playlist in sources.json, merges entries that are the same
channel (using channels.json aliases and the iptv-org channel database),
checks which streams respond, and writes every addon endpoint as a plain
JSON file under ./dist, ready to be served by GitHub Pages.

Usage: python3 build.py [--out DIR] [--base-url URL] [--no-check]
"""
import argparse
import concurrent.futures
import gzip
import html
import json
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent
ASSETS_DIR = ROOT / "assets"
LOGOS_DIR = ASSETS_DIR / "logos"
IPTV_DB = "https://iptv-org.github.io/api"
ID_PREFIX = "iltv_"
CATALOG_ID = "iltv"
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"

MANIFEST = {
    "id": "community.iptv.israel",
    "version": "1.1.0",
    "name": "Israeli TV",
    "description": "Live Israeli TV channels from several public playlists, with multiple sources per channel. Updated automatically.",
    "resources": ["catalog", "meta", "stream"],
    "types": ["tv"],
    "idPrefixes": [ID_PREFIX],
    "behaviorHints": {"configurable": False},
}

ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
QUALITY_RE = re.compile(r"\s*\((\d+p)\)")
TAG_RE = re.compile(r"\s*\[([^\]]*)\]")
# Variant suffixes in tvg-ids, e.g. kan11_hevc, reshet13_src2.
VARIANT_RE = re.compile(r"_(hevc|subs|src\d+)$")
VARIANT_LABELS = {"hevc": "HEVC", "subs": "Subtitles"}
VARIANT_RANK = {"hevc": 2, "subs": 1}


def fetch(source, timeout=60):
    if re.match(r"https?://", source):
        req = urllib.request.Request(source, headers={"User-Agent": "stremio-il-builder"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    return (ROOT / source).read_text(encoding="utf-8")


def fetch_json(url):
    try:
        return json.loads(fetch(url))
    except Exception as e:
        print(f"warning: could not load {url}: {e}", file=sys.stderr)
        return []


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


def load_db():
    """Channel names and logos from the iptv-org database, keyed by channel id."""
    names = {c["id"]: c["name"] for c in fetch_json(f"{IPTV_DB}/channels.json")}
    logos = {}
    for l in fetch_json(f"{IPTV_DB}/logos.json"):
        if l.get("feed") or not l.get("in_use", True):
            continue
        # Prefer raster formats (not every Stremio client renders SVG), then the widest.
        score = (l.get("format") != "SVG", l.get("width") or 0)
        if l["channel"] not in logos or score > logos[l["channel"]][0]:
            logos[l["channel"]] = (score, l["url"])
    return names, {k: v[1] for k, v in logos.items()}


def resolve(entry, config):
    """Return (canonical channel id, variant) for a playlist entry."""
    raw = entry["attrs"].get("tvg-id", "").split("@")[0]
    base, variant = raw, None
    m = VARIANT_RE.search(raw)
    if m:
        base, variant = raw[:m.start()], m.group(1)
    aliases = config["aliases"]
    canon = aliases.get(raw) or aliases.get(base) or base
    if not canon:
        canon = TAG_RE.sub("", QUALITY_RE.sub("", entry["title"])).strip()
    return canon, variant


def clean_name(title):
    name = TAG_RE.sub("", QUALITY_RE.sub("", title)).strip()
    return re.sub(r"\s*\(Israel\)", "", name)


def build_channels(sources, config, db_names, db_logos, base_url):
    """Merge every source's entries into channels with one or more streams."""
    channels, seen_urls = {}, set()
    for prio, (src, entries) in enumerate(sources):
        for e in entries:
            # YouTube channel pages aren't playable stream URLs.
            if e["url"] in seen_urls or "youtube.com" in e["url"]:
                continue
            seen_urls.add(e["url"])
            canon, variant = resolve(e, config)
            cid = ID_PREFIX + slugify(canon)
            attrs, title = e["attrs"], e["title"]
            custom = config["channels"].get(canon, {})

            ch = channels.get(cid)
            if ch is None:
                genres = custom.get("genres") or [
                    config["genres"].get(g.strip(), g.strip())
                    for g in attrs.get("group-title", "").split(";") if g.strip()
                ] or ["Other"]
                ch = channels[cid] = {
                    "id": cid,
                    "name": custom.get("name") or db_names.get(canon) or clean_name(title),
                    "logo": None,
                    "genres": genres,
                    "streams": [],
                }
            if not ch["logo"]:
                logo = attrs.get("tvg-logo", "")
                if logo.startswith("http"):
                    ch["logo"] = logo
                elif canon in db_logos:
                    ch["logo"] = db_logos[canon]
                elif (LOGOS_DIR / f"{canon}.png").exists():
                    ch["logo"] = f"{base_url.rstrip('/')}/logos/{canon}.png"

            quality = QUALITY_RE.search(title)
            ch["streams"].append({
                "url": e["url"],
                "source": src["label"],
                "priority": prio,
                "variant": variant,
                "quality": quality.group(1) if quality else None,
                "tags": TAG_RE.findall(title),
                "headers": e["headers"],
                "ok": None,
            })
    return sorted(channels.values(), key=lambda c: c["name"].lower())


def probe(stream):
    """True if the URL returns an HLS playlist. Run from GitHub's US servers,
    so geo-blocked Israeli streams may fail here and still work in Israel."""
    url = stream["url"]
    if not url.startswith("http"):
        return None
    headers = {"User-Agent": BROWSER_UA, "Accept-Encoding": "gzip", **stream["headers"]}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as r:
            body = r.read(4096)
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        return b"#EXTM3U" in body[:512]
    except Exception:
        # A truncated gzip read lands here too; treat any failure as down.
        return False


def check_streams(channels):
    streams = [s for ch in channels for s in ch["streams"]]
    with concurrent.futures.ThreadPoolExecutor(32) as pool:
        for s, ok in zip(streams, pool.map(probe, streams)):
            s["ok"] = ok


def needs_proxy(s):
    return s["url"].startswith("http://") or bool(s["headers"])


def sort_streams(ch):
    # Working streams first, then plain over HEVC/subtitle variants, then direct
    # https streams (play everywhere, incl. web) over ones needing the proxy,
    # then source priority.
    ch["streams"].sort(key=lambda s: (s["ok"] is False, VARIANT_RANK.get(s["variant"], 0),
                                      needs_proxy(s), s["priority"]))


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
    n = len(ch["streams"])
    meta["description"] = (f"{ch['name']} — live. {n} source{'s' if n > 1 else ''}. "
                           f"If one doesn't play, try the next. Genres: {', '.join(ch['genres'])}.")
    return meta


def stremio_stream(s, idx):
    details = [s["source"], VARIANT_LABELS.get(s["variant"]), s["quality"], *s["tags"]]
    stream = {
        "url": s["url"],
        "name": f"Source {idx + 1}",
        "title": " · ".join(x for x in details if x),
    }
    hints = {}
    # Plain-http streams and streams needing custom headers can't play
    # directly in a browser; notWebReady routes them through Stremio's
    # local streaming server, which is also what applies proxyHeaders.
    if needs_proxy(s):
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
<li>Pick a genre (optional), choose a channel, then pick a source (Source 1 is usually the best).</li>
</ol></section>

<section class="card"><h2>Genres</h2><div class="tags">{"".join(f"<span>{e(g)}</span>" for g in genres)}</div></section>

<section class="card"><h2>Good to know</h2><ul class="muted" style="margin:0;padding-left:20px">
<li>The Stremio <b>desktop, Android or TV</b> app is recommended. Some streams don't play on web.stremio.com.</li>
<li>Many channels are geo-restricted and only play from Israel.</li>
<li>Each channel can have several sources. If one doesn't play, go back and pick the next one.</li>
<li>Streams come from public playlists (<a href="https://github.com/iptv-org/iptv">iptv-org</a>, <a href="https://github.com/il90il90/m3u-tv">il90il90/m3u-tv</a>, <a href="https://github.com/Free-TV/IPTV">Free-TV</a>); some may be offline at times.</li>
</ul></section>
<p class="muted">Source code: <a href="https://github.com/Mudales/stremio-tv-il">github.com/Mudales/stremio-tv-il</a></p>
</main></body></html>
"""
    (out / "index.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="dist")
    ap.add_argument("--base-url", default="", help="Public URL of the site (logos and install page)")
    ap.add_argument("--no-check", action="store_true", help="Skip probing streams")
    args = ap.parse_args()

    config = json.loads((ROOT / "channels.json").read_text(encoding="utf-8"))
    sources = []
    for src in json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))["sources"]:
        try:
            entries = list(parse_m3u(fetch(src["url"])))
        except Exception as e:
            print(f"warning: skipping source {src['id']}: {e}", file=sys.stderr)
            continue
        print(f"source {src['id']}: {len(entries)} entries")
        sources.append((src, entries))

    db_names, db_logos = load_db()
    channels = build_channels(sources, config, db_names, db_logos, args.base_url)
    if not channels:
        raise SystemExit("Playlists parsed to zero channels; refusing to publish an empty addon.")
    if not args.no_check:
        check_streams(channels)
    for ch in channels:
        sort_streams(ch)

    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ASSETS_DIR, out)

    genres = sorted({g for ch in channels for g in ch["genres"]})
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
        write_json(out / "stream" / "tv" / f"{ch['id']}.json",
                   {"streams": [stremio_stream(s, i) for i, s in enumerate(ch["streams"])]})

    # Probe results, for debugging dead channels (as seen from the build machine).
    write_json(out / "status.json", {
        "built": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "channels": [{"id": ch["id"], "name": ch["name"],
                      "streams": [{"source": s["source"], "variant": s["variant"],
                                   "ok": s["ok"], "url": s["url"]} for s in ch["streams"]]}
                     for ch in channels],
    })

    (out / ".nojekyll").write_text("")
    write_index(out, args.base_url, len(channels), genres)
    streams = [s for c in channels for s in c["streams"]]
    print(f"Built {len(channels)} channels, {len(streams)} streams "
          f"({sum(s['ok'] is True for s in streams)} responding), {len(genres)} genres -> {out}/")
    no_logo = [c["name"] for c in channels if not c["logo"]]
    if no_logo:
        print(f"channels without a logo: {', '.join(no_logo)}")


if __name__ == "__main__":
    main()
