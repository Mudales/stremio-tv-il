# Israeli TV — Stremio addon

A free, serverless Stremio addon for live Israeli TV channels, built from the
public [iptv-org](https://github.com/iptv-org/iptv) playlist
(`countries/il.m3u`) and hosted on GitHub Pages.

## How it works

- `build.py` downloads the playlist and writes every addon endpoint
  (`manifest.json`, catalog, meta, stream) as static JSON into `dist/`.
- The GitHub Actions workflow runs it on every push and **every 6 hours**,
  then deploys `dist/` to GitHub Pages. No server, no domain, no cost.

## Setup

1. Push this repo to GitHub (public).
2. Repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
3. Run the workflow once (**Actions → Build & deploy addon → Run workflow**), or just push.
4. Open `https://<user>.github.io/<repo>/` and click **Install in Stremio**,
   or paste `https://<user>.github.io/<repo>/manifest.json` into Stremio's addon search.

## Build locally

```bash
python3 build.py            # outputs to dist/
python3 -m http.server -d dist 8080
```

## Notes

- Most streams are plain `http://` or need a custom User-Agent, so they play in
  the **desktop / Android / TV** apps but not on web.stremio.com.
- Many channels are geo-restricted to Israel.
- Stream availability depends entirely on the upstream playlist.
