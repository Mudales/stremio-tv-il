<p align="center">
  <img src="assets/logo.png" width="128" alt="Israeli TV for Stremio">
</p>

<h1 align="center">Israeli TV for Stremio</h1>

<p align="center">
  Live Israeli TV channels in Stremio. Free, no account, no server.
</p>

<p align="center">
  <a href="https://mudales.github.io/stremio-tv-il/"><img src="https://img.shields.io/badge/Install-Stremio%20addon-2457d6?style=for-the-badge" alt="Install"></a>
  <a href="https://github.com/Mudales/stremio-tv-il/actions/workflows/build.yml"><img src="https://img.shields.io/github/actions/workflow/status/Mudales/stremio-tv-il/build.yml?style=for-the-badge&label=build" alt="Build status"></a>
</p>

---

## Install

**Option 1: install page (easiest)**
Open **<https://mudales.github.io/stremio-tv-il/>** and click **Open in Stremio app**.

**Option 2: paste the URL**
In Stremio, go to **Addons**, paste this into the search box, and press **Install**:

```
https://mudales.github.io/stremio-tv-il/manifest.json
```

**Option 3: Stremio Web**
[Install via web.stremio.com](https://web.stremio.com/#/addons?addon=https%3A%2F%2Fmudales.github.io%2Fstremio-tv-il%2Fmanifest.json)

## How to watch

1. Install the addon (see above).
2. In Stremio go to **Discover → TV → Israeli TV**.
3. Optionally filter by genre (News, Kids, Sports, Movies, …), pick a channel, and press play.

Channels include Kan 11, Keshet 12, Channel 13, Now 14, i24NEWS, the Knesset Channel, Kan Educational, kids channels, and more.

## Good to know

- **Use the desktop, Android, or TV app.** Most streams are plain `http://` or need a custom
  User-Agent, which browsers block, so they won't play on web.stremio.com.
- **Geo-restrictions:** many channels only play from an Israeli IP address.
- **Availability:** streams come from the community-maintained
  [iptv-org](https://github.com/iptv-org/iptv) playlist. Some channels may be offline at any
  given time; fixes upstream are picked up automatically on the next rebuild.

## How it works

A Stremio addon is just a set of JSON URLs (`manifest.json`, catalog, meta, stream). For a fixed
channel list, all of them can be generated ahead of time, so the whole addon is a **static site**
hosted for free on GitHub Pages.

```
iptv-org il.m3u ──► build.py ──► dist/*.json ──► GitHub Pages ──► Stremio
                      ▲
        GitHub Actions: on push + every 6 hours
```

- [`build.py`](build.py) downloads the playlist, groups entries into channels, and writes every
  endpoint as a JSON file (Python standard library only, nothing to install).
- [`.github/workflows/build.yml`](.github/workflows/build.yml) runs the build on every push and
  every 6 hours, then deploys `dist/` to GitHub Pages.
- Streams that need special headers get `behaviorHints.proxyHeaders`, so Stremio's streaming
  server sends the right User-Agent / Referer.

### Build locally

```bash
python3 build.py
python3 -m http.server -d dist 8080
```

Then open <http://localhost:8080/>.

### Fork your own

1. Fork this repo.
2. **Settings → Pages → Source: GitHub Actions**.
3. **Actions → Build & deploy addon → Run workflow**.
4. Your addon is live at `https://<you>.github.io/<repo>/manifest.json`.

To use a different country, change `PLAYLIST_URL` in `build.py` to another
[iptv-org playlist](https://github.com/iptv-org/iptv#grouped-by-country).

## Disclaimer

This addon doesn't host any content. It only links to publicly listed streams from the
iptv-org playlist. All channels and trademarks belong to their respective owners.
