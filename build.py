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
import urllib.request
from pathlib import Path

PLAYLIST_URL = "https://iptv-org.github.io/iptv/countries/il.m3u"
ID_PREFIX = "iltv_"
CATALOG_ID = "iltv"

MANIFEST = {
    "id": "community.iptv.israel",
    "version": "1.0.0",
    "name": "Israeli TV",
    "description": "Live Israeli TV channels from the public iptv-org playlist. Updated automatically.",
    "logo": "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d4/Flag_of_Israel.svg/320px-Flag_of_Israel.svg.png",
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


def write_index(out, base_url, count):
    manifest_url = f"{base_url.rstrip('/')}/manifest.json" if base_url else "manifest.json"
    stremio_url = re.sub(r"^https?://", "stremio://", manifest_url) if base_url else "#"
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Israeli TV · Stremio addon</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:560px;margin:48px auto;padding:0 16px;line-height:1.5;background:#0f1115;color:#e8e8e8}}
a.btn{{display:inline-block;background:#7b5bf5;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:600}}
code{{background:#1c1f26;padding:2px 6px;border-radius:4px;word-break:break-all}}
</style></head><body>
<h1>Israeli TV for Stremio</h1>
<p>{count} live channels from the public <a style="color:#9d86ff" href="https://github.com/iptv-org/iptv">iptv-org</a> playlist, rebuilt automatically.</p>
<p><a class="btn" href="{html.escape(stremio_url)}">Install in Stremio</a></p>
<p>Or paste this URL into Stremio → Addons → search box:<br><code>{html.escape(manifest_url)}</code></p>
</body></html>
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
    manifest = dict(MANIFEST)
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
    write_index(out, args.base_url, len(channels))
    print(f"Built {len(channels)} channels, {sum(len(c['streams']) for c in channels)} streams, "
          f"{len(genres)} genres -> {out}/")


if __name__ == "__main__":
    main()
