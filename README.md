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
3. Optionally filter by genre (News, Kids, Sports, Movies, …) and pick a channel.
4. Pick a source. **Source 1 is usually the best**; if it doesn't play, go back and try the next one.

60+ channels, including Kan 11, Keshet 12, Channel 13, Now 14, Channel 9, i24NEWS, Sport 5, ONE,
Viva, the Knesset Channel, Kan Educational, kids channels, and more. The main channels have
several sources each, including HEVC and Hebrew-subtitled versions.

## Good to know

- **Desktop, Android, or TV app recommended.** Some streams are plain `http://` or need a custom
  User-Agent, which browsers block, so those won't play on web.stremio.com.
- **Geo-restrictions:** many channels only play from an Israeli IP address.
- **Availability:** streams come from community-maintained playlists (see [Sources](#sources)).
  Some may be offline at any given time; fixes upstream are picked up automatically on the
  next rebuild.
- **HEVC sources** use less bandwidth but may not play on older devices.

## How it works

A Stremio addon is just a set of JSON URLs (`manifest.json`, catalog, meta, stream). For a fixed
channel list, all of them can be generated ahead of time, so the whole addon is a **static site**
hosted for free on GitHub Pages.

```
playlists (sources.json) ──► build.py ──► dist/*.json ──► GitHub Pages ──► Stremio
                               ▲
                 GitHub Actions: on push + every 6 hours
```

- [`build.py`](build.py) downloads every playlist, merges entries that are the same channel into
  one channel with several sources, probes each stream, and writes every endpoint as a JSON file
  (Python standard library only, nothing to install).
- Sources are ordered: **responding streams first**, then plain over HEVC/subtitle versions,
  then direct `https` streams over ones that need Stremio's proxy, then playlist priority.
  The probe runs on GitHub's servers in the US, so a geo-blocked stream can look down there
  and still play in Israel; nothing is hidden, it only moves down the list.
  Probe results are published at [`status.json`](https://mudales.github.io/stremio-tv-il/status.json).
- [`.github/workflows/build.yml`](.github/workflows/build.yml) runs the build on every push and
  every 6 hours, then deploys `dist/` to GitHub Pages.
- Streams that need special headers get `behaviorHints.proxyHeaders`, so Stremio's streaming
  server sends the right User-Agent / Referer.

## Sources

| Playlist | Label in Stremio |
|---|---|
| [iptv-org](https://github.com/iptv-org/iptv) `countries/il.m3u` | `iptv-org` |
| [il90il90/m3u-tv](https://github.com/il90il90/m3u-tv) | `FreeTV` |
| [Free-TV/IPTV](https://github.com/Free-TV/IPTV) `playlist_israel.m3u8` | `Free-TV` |

- **Add a playlist:** add an entry to [`sources.json`](sources.json). Order is priority.
- **Merge channels across playlists:** playlists name channels differently (`kan11`,
  `Kan11.il@SD`, …). [`channels.json`](channels.json) maps each playlist's `tvg-id` to one
  canonical [iptv-org channel id](https://iptv-org.github.io/api/channels.json); names and logos
  come from the iptv-org database. Channels it doesn't know get a name and genre in
  `channels.json` and a logo in [`assets/logos/`](assets/logos).

### Build locally

```bash
python3 build.py            # add --no-check to skip probing streams
python3 -m http.server -d dist 8080
```

Then open <http://localhost:8080/>.

### Fork your own

1. Fork this repo.
2. **Settings → Pages → Source: GitHub Actions**.
3. **Actions → Build & deploy addon → Run workflow**.
4. Your addon is live at `https://<you>.github.io/<repo>/manifest.json`.

To use a different country, point [`sources.json`](sources.json) at other playlists, e.g. an
[iptv-org country playlist](https://github.com/iptv-org/iptv#grouped-by-country).

## Disclaimer

This addon doesn't host any content. It only links to publicly listed streams from the
playlists above. All channels and trademarks belong to their respective owners.
