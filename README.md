# Storage Rent Watch

Static directory of self-storage renter rules by US state and city: rent increases, late fees, lien sales and auctions, how to stop a sale, and cheaper storage. Adapted from Curbside Rules' build system.

- `site.config.json`: site name, base_url/base_path, `states`, paid partner slots (`affiliates`), free legal help links (`legal_help`)
- `content/pages/<folder>/<slug>.md`: one guide per file (JSON front matter + Markdown). Folder = `national`, a state-name slug (`indiana`) or a city slug (`indianapolis`)
- `content/_templates/guide-template.md`: copy this for a new guide
- `content/about.md`, `content/disclosure.md`: static pages (`/free-legal-help/` is generated from config)
- `templates/base.html`, `static/`: layout, CSS, favicon
- `build.py`: builds everything into `docs/` (stdlib only)
- `scripts/check.py`: local server + crawler QA (`--external` also pings outside links)
- `pages-queue.json`: the nightly page queue
- `NIGHTLY.md`: the nightly routine, step by step

Build: `python3 build.py && python3 scripts/check.py`

Live: https://funnyfarm4.github.io/storage-rent-watch/
