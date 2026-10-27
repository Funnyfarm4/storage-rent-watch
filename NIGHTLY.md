# Storage Rent Watch: publishing one new page per night

Repo: `/workspace/storage-rent-watch` (GitHub: `Funnyfarm4/storage-rent-watch`, Pages from `main` `/docs`).
Live: https://funnyfarm4.github.io/storage-rent-watch/ (base path `/storage-rent-watch/`).
Only Python 3 is needed. Target time: 45-60 minutes. One page per night.

## 1. Pick the page

Open `pages-queue.json`. Take the first entry with `"status": "queued"` and `"priority": "high"`; if none, the queued entry with the lowest `n`. Note `scope`, `state`, `city`, `topic`, `slug`, `start_with_statute`, `official_text_at` and `legal_aid_to_verify`. Those hints are from memory and are **not verified**.

## 2. Source rules (non-negotiable)

- **Statute facts come from statute text.** Prefer the state legislature's official code site. A reliable full-text copy (Justia, Cornell LII) is OK when the official site is a script-only app, but fetch it yourself, read the actual section, and cite each section separately. Agency pages (attorney general, unclaimed property office, courts) are fine for agency facts.
- **Fetch every source today** and set its `checked` date to today. Never cite a page you didn't open.
- **Never invent or estimate numbers.** No storage prices, average rents, percentages or "X% cheaper" unless an official source states them. Partner marketing claims may be quoted only with attribution ("Neighbor advertises...").
- **No news, Reddit, X or blog posts as sources.** They're fine for ideas and FAQ wording only.
- If you can't verify something, **leave it out** and mention it in your report. If two official sources disagree, use the more specific one and note the conflict.
- Write in plain English, calm and respectful. Not legal advice; the build adds the "not legal advice" line automatically.
- No traffic claims anywhere.

### Research checklist for a state auction-rules page

- [ ] Chapter name and citation; what the renter is called (renter, occupant, tenant)
- [ ] When default starts and when enforcement can begin (lockout, moving property)
- [ ] Notice: who gets it, delivery methods (mail, certified, email conditions), required contents, minimum days to pay
- [ ] Advertising: newspaper/online, how many times, required contents
- [ ] Earliest sale date rules; where the sale may be held (online allowed?)
- [ ] Redemption: how to stop the sale, what must be paid, what happens after paying
- [ ] Late fee caps; collection/enforcement costs
- [ ] Leftover proceeds: who holds them, how long, which unclaimed property office (link the official claim site)
- [ ] Vehicles/boats; value-limit clauses; anything unusual (e.g. Ohio bans living in units)
- [ ] 3-6 real FAQ questions

## 3. Free legal help rule (required)

- Every page with `topic` `auction-rules`, `stop-auction` or `rent-increase` **must** include `{{legal-help}}`. The build fails without it.
- The box pulls links from `site.config.json` -> `legal_help`: national (LawHelp.org, LSC's find-legal-aid page, ABA Free Legal Answers) plus the page's state.
- **When you publish the first page for a new state**, add that state to `states` and to `legal_help.states` with its statewide legal aid site(s) (e.g. TexasLawHelp.org). Open each URL today and confirm it's the real nonprofit/court/bar site. **Drop any URL that doesn't load or isn't what it claims.** Set `aba_free_legal_answers` to `true` only if the state is on the participating-state list at https://www.abafreelegalanswers.org/. Update `legal_help.checked` to today.
- These are **free or low-cost services, not paid partners**: never use tracking links, `data-affiliate` or `rel="sponsored"` in them. `scripts/check.py` fails if a legal-help box contains a paid link.

## 4. Write the source file

```
cp content/_templates/guide-template.md content/pages/<folder>/<slug>.md
```

- `<folder>`: `national` for national pages, the state-name slug for state pages (`texas`, `new-york`), the city slug for city pages (`houston`, `new-york-city`). The file name must equal `slug`. The build checks both.
- URLs: national `/<slug>/`, state `/<state-name>/<slug>/`, city `/<city>/<slug>/`. A city slug may not equal a state slug (use "New York City").
- Front matter is JSON between `---json` and `---`. Required: `title, description, scope, topic, label, slug, published, updated, last_checked, sources`; plus `state` (state and city pages) and `city` (city pages). Optional: `seo_title, quick_facts, faq, partners, partner_heading, partner_intro, sources_note`.
- `topic` is one of `auction-rules`, `stop-auction`, `rent-increase`, `cheap-storage`. `label` is the short breadcrumb name.
- `description`: max 160 characters and unique.
- Each source needs `id, publisher, title, url, checked`. Cite inline as `[[id]]`. The build fails if a source is never cited or an `[[id]]` doesn't exist.
- Markdown: `##`/`###` headings, paragraphs, `-` and `1.` lists (no nested lists; use `###` steps instead), `**bold**`, `*italic*`, `[text](url)`, `> note`, `{{legal-help}}`, `{{partner-box}}`.
- `{{partner-box}}` shows the paid partner slots (SpareFoot, Storage.com, Neighbor), labeled "Paid partner link", and automatically adds the FTC disclosure at the top. Use it where comparing storage genuinely helps (rent increases, cheap storage, after redeeming). Optional `"partners": ["neighbor"]` limits which show.
- Link internally to the matching state/national pages.

## 5. Build and check

```
cd /workspace/storage-rent-watch
python3 build.py && python3 scripts/check.py
python3 scripts/check.py --external   # pings every outside link
```

`build.py` must end with no BUILD ERRORS and `check.py` must print **"All checks passed."** Fix anything under PROBLEMS before deploying. In `--external`, WARN 403 from Justia and leginfo.legislature.ca.gov is normal (bot blocking); any ERR means a dead link: replace it or drop that fact.

## 6. Update the queue

In `pages-queue.json`, set the entry's `"status": "published"`, add `"published_url"`, and append `{"url_path": ..., "published": "YYYY-MM-DD"}` to `published`. Add new ideas you found to the end of `queue` (next `n`).

## 7. Commit and push

```
git add -A
git commit -m "Add <title>"
git push origin main
```

The box's `gh` CLI is signed in as Funnyfarm4 and is the git credential helper. Then verify (GitHub Pages takes 1-10 minutes):

```
for u in "" <new/url/path/> sitemap.xml; do
  printf "%s " "$u"; curl -s -o /dev/null -w "%{http_code}\n" "https://funnyfarm4.github.io/storage-rent-watch/$u"
done
```

All must return 200.

## 8. Report

Tell Wesley (chat and Telegram): page title + live URL, the statute/sources used, anything left out because it couldn't be verified, and any new legal-aid links added. Never make traffic or earnings claims you can't show.

## Paid partner links

When a program approves us, paste the tracking link into `site.config.json` -> `affiliates.<key>.tracking_url`, rebuild, check, push. Until then links go to the partner's plain public site. Never sign up for programs or email partners from the nightly routine.
