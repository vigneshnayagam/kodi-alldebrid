# AllDebrid Kodi Addon — Developer Guide

## Project structure

```
kodi_agent/
├── plugin.video.alldebrid/   # Addon source code
│   ├── addon.py              # Main router and UI builders
│   ├── addon.xml             # Addon manifest and version
│   └── resources/
│       ├── settings.xml      # Kodi settings definitions
│       └── lib/
│           ├── alldebrid.py  # AllDebrid REST API wrapper
│           ├── auth.py       # PIN authentication flow
│           ├── constants.py  # API URLs, status codes, extensions
│           ├── library.py    # Kodi library integration (.strm/.nfo)
│           ├── metadata.py   # Filename parser + TMDB API client
│           ├── player.py     # Link resolution, playback, resume
│           ├── resume.py     # Playback position persistence
│           └── utils.py      # Formatting, logging, settings helpers
├── repo/                     # Built distribution artifacts (committed to main)
│   ├── addons.xml            # Kodi repo manifest (stable builds only)
│   ├── addons.xml.md5
│   ├── plugin.video.alldebrid/
│   │   ├── plugin.video.alldebrid-<version>.zip   # Stable zip
│   │   └── dev/
│   │       └── plugin.video.alldebrid-<version>.zip  # Dev/experimental zip
│   └── repository.alldebrid/
└── generate_repo.py          # Build script
```

## Building and distributing

### Stable release (from main, after merging a tested feature branch)

```bash
python3 generate_repo.py
git add repo/ plugin.video.alldebrid/
git commit -m "vX.Y.Z: description"
git push
```

This updates `addons.xml` so existing Kodi installs receive an update notification.

### Dev/experimental build (from a feature branch, for testing before merging)

```bash
python3 generate_repo.py --dev
git add repo/plugin.video.alldebrid/dev/ repo/plugin.video.alldebrid/index.html repo/index.html
git commit -m "Dev build: description"
git push
```

This drops the zip into `repo/plugin.video.alldebrid/dev/` without touching `addons.xml`, so stable installs are unaffected.

To install the dev build in Kodi:
> Add-ons → Install from zip file → AllDebrid Repo → `plugin.video.alldebrid/` → `dev/` → zip file

## Branching workflow

The repo on `main` always contains stable, working source code. Feature work lives on branches and is only merged to `main` once tested.

```
1.  git checkout -b feature/my-feature
2.  # ... develop and commit ...
3.  python3 generate_repo.py --dev   # build experimental zip
4.  git add repo/plugin.video.alldebrid/dev/ repo/plugin.video.alldebrid/index.html repo/index.html
5.  git commit -m "Dev build: my-feature"
6.  git push                          # GitHub Pages serves the dev zip
7.  # Install dev zip in Kodi and test on Android TV
8.  # Once happy:
9.  git checkout main
10. git merge feature/my-feature
11. python3 generate_repo.py          # update stable repo
12. git add repo/ plugin.video.alldebrid/
13. git commit -m "vX.Y.Z: my-feature"
14. git push
```

Key rules:
- **Never commit `repo/` stable artifacts from a feature branch** — only the `dev/` subfolder
- **Never run `generate_repo.py` (without `--dev`) from a feature branch** — it would update `addons.xml` with unmerged code
- Only `main` runs the stable build

## Kodi repo URL

GitHub Pages URL: `https://vigneshnayagam.github.io/kodi-alldebrid/repo/`

Add this as a file source in Kodi to browse and install from the repo.

## AllDebrid API

- Base URL: `https://api.alldebrid.com`
- Auth: Bearer token (obtained via PIN flow at `/v4.1/pin/get` + `/v4.1/pin/check`)
- Magnet status uses `/v4.1/magnet/status`; all other endpoints use `/v4`

## TMDB integration

The addon uses the TMDB v3 API for movie/TV metadata when syncing to the Kodi library. A default API key is shipped in `constants.py`. Users can override it in Settings → Library → TMDB API Key.

Cached responses live at `special://profile/addon_data/plugin.video.alldebrid/tmdb_cache.json` (30-day expiry).

## Library integration setup (one-time, on the Kodi device)

After the first "Sync to Library" or "Sync All to Library":

1. In Kodi: Settings → Media → Videos → Add Videos
2. Browse to `special://profile/strm/Movies` — set content to **Movies**, scraper to **Local information only**
3. Repeat for `special://profile/strm/TVShows` — set content to **TV Shows**, scraper to **Local information only**

The addon writes `.strm` + `.nfo` files there; Kodi reads them as regular library entries with TMDB artwork and metadata.
