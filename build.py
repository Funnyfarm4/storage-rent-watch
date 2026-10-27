#!/usr/bin/env python3
"""Storage Rent Watch static site builder. Standard library only (Python 3.8+).
Adapted from Curbside Rules' build.py.

Usage:  python3 build.py
Reads   site.config.json, content/pages/<folder>/<slug>.md, templates/base.html, static/*
Writes  docs/  (deployable as-is to GitHub Pages "/docs")

Page scopes (front-matter "scope"):
  national -> /<slug>/               (folder content/pages/national/)
  state    -> /<state-name-slug>/<slug>/   e.g. /indiana/storage-auction-rules/
  city     -> /<city-slug>/<slug>/         e.g. /indianapolis/cheap-storage/
"""
import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "site.config.json").read_text())
OUT = ROOT / CONFIG.get("output_dir", "docs")
BASE = CONFIG["base_url"].rstrip("/")
BASE_PATH = "/" + CONFIG.get("base_path", "/").strip("/") + "/"
if BASE_PATH == "//":
    BASE_PATH = "/"
STATES = CONFIG["states"]
LEGAL = CONFIG["legal_help"]
# Topics that MUST carry the {{legal-help}} box (auction, stop-auction and rent-increase pages).
LEGAL_TOPICS = {"auction-rules", "stop-auction", "rent-increase"}
RESERVED = {"about", "disclosure", "free-legal-help", "404.html", "sitemap.xml", "robots.txt", "style.css", "favicon.svg"}


def with_base(html_text):
    """Prefix every root-relative href/src ("/x", not "//x") with base_path."""
    if BASE_PATH == "/":
        return html_text
    return re.sub(r'((?:href|src)=")/(?!/)', lambda m: m.group(1) + BASE_PATH, html_text)
TEMPLATE = (ROOT / "templates" / "base.html").read_text()
SOURCES_NOTE = ("Every rule, deadline and fee on this page comes from the statute text or official pages listed here. "
                "Laws change and your rental agreement matters too, so check the current law and talk to a lawyer or legal aid office about your situation.")
TOPIC_LABELS = {"auction-rules": "Auction & lien rules", "stop-auction": "Stop an auction", "rent-increase": "Rent increases",
                "cheap-storage": "Cheaper storage"}
ERRORS = []


def esc(s):
    return html.escape(str(s), quote=True)


# ---------------------------------------------------------------- markdown
def inline(text, sources=None, src_used=None):
    """Tiny inline Markdown: escapes HTML, then **bold**, *em*, [text](url), [[source-id]]."""
    out = esc(text)

    def cite(m):
        sid = m.group(1)
        if sources is None or sid not in sources:
            ERRORS.append(f"unknown source id [[{sid}]]")
            return m.group(0)
        if src_used is not None:
            src_used.add(sid)
        s = sources[sid]
        n = s["_n"]
        return (f'<a class="cite" href="{esc(s["url"])}" rel="noopener" '
                f'title="{esc(s["title"])} (last checked {esc(s["_checked"])})">'
                f'{esc(s["publisher"])}<sup>[{n}]</sup></a>')

    out = re.sub(r"\[\[([a-z0-9_-]+)\]\]", cite, out)
    out = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", out)
    out = re.sub(r"(?<![\*\w])\*(?!\s)(.+?)(?<!\s)\*(?![\*\w])", r"<em>\1</em>", out)

    def link(m):
        label, url = m.group(1), html.unescape(m.group(2))
        ext = url.startswith("http")
        rel = ' rel="noopener"' if ext else ""
        return f'<a href="{esc(url)}"{rel}>{label}</a>'

    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, out)
    return out


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def markdown(md, sources=None, src_used=None, shortcodes=None, toc=None):
    """Block Markdown subset: ## / ### headings, paragraphs, - lists, 1. lists, > notes, {{shortcodes}}."""
    lines = md.strip("\n").split("\n")
    html_out, para, lst, lst_type = [], [], [], None

    def flush_para():
        nonlocal para
        if para:
            html_out.append(f"<p>{inline(' '.join(para), sources, src_used)}</p>")
            para = []

    def flush_list():
        nonlocal lst, lst_type
        if lst:
            items = "".join(f"<li>{inline(i, sources, src_used)}</li>" for i in lst)
            html_out.append(f"<{lst_type}>{items}</{lst_type}>")
            lst, lst_type = [], None

    for raw in lines:
        line = raw.rstrip()
        sc = re.fullmatch(r"\{\{\s*([a-z0-9-]+)\s*\}\}", line.strip())
        if sc:
            flush_para(); flush_list()
            name = sc.group(1)
            if shortcodes and name in shortcodes:
                html_out.append(shortcodes[name]())
            else:
                ERRORS.append(f"unknown shortcode {{{{{name}}}}}")
            continue
        h = re.match(r"^(#{2,3})\s+(.*)$", line)
        ul = re.match(r"^\s*[-*]\s+(.*)$", line)
        ol = re.match(r"^\s*\d+\.\s+(.*)$", line)
        bq = re.match(r"^>\s?(.*)$", line)
        if h:
            flush_para(); flush_list()
            lvl, text = len(h.group(1)), h.group(2)
            hid = slugify(re.sub(r"\[\[.*?\]\]", "", text))
            if toc is not None and lvl == 2:
                toc.append((hid, text))
            html_out.append(f'<h{lvl} id="{hid}">{inline(text, sources, src_used)}</h{lvl}>')
        elif ul or ol:
            flush_para()
            t = "ul" if ul else "ol"
            if lst_type and lst_type != t:
                flush_list()
            lst_type = t
            lst.append((ul or ol).group(1))
        elif bq:
            flush_para(); flush_list()
            html_out.append(f'<p class="note">{inline(bq.group(1), sources, src_used)}</p>')
        elif not line.strip():
            flush_para(); flush_list()
        elif lst and raw.startswith("  "):
            lst[-1] += " " + line.strip()
        else:
            flush_list()
            para.append(line.strip())
    flush_para(); flush_list()
    return "\n".join(html_out)



# ---------------------------------------------------------------- content
def state_slug(code):
    return slugify(STATES[code])


def load_page(path):
    text = path.read_text()
    m = re.match(r"^---json\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        ERRORS.append(f"{path}: missing ---json front matter")
        return None
    try:
        meta = json.loads(m.group(1))
    except json.JSONDecodeError as e:
        ERRORS.append(f"{path}: bad JSON front matter: {e}")
        return None
    meta["body"] = m.group(2)
    meta["_path"] = path
    required = ["title", "description", "scope", "topic", "label", "slug", "published", "updated", "last_checked", "sources"]
    for k in required:
        if k not in meta:
            ERRORS.append(f"{path}: missing front-matter key '{k}'")
    if not meta.get("sources"):
        ERRORS.append(f"{path}: no sources")
    if len(meta.get("description", "")) > 160:
        ERRORS.append(f"{path}: description is {len(meta['description'])} chars (max 160)")
    scope = meta.get("scope")
    if scope not in ("national", "state", "city"):
        ERRORS.append(f"{path}: scope must be national, state or city")
        return None
    if scope != "national":
        if meta.get("state") not in STATES:
            ERRORS.append(f"{path}: state '{meta.get('state')}' missing from site.config.json 'states'")
            return None
        meta["state_name"] = STATES[meta["state"]]
        meta["state_slug"] = state_slug(meta["state"])
    if scope == "city":
        if not meta.get("city"):
            ERRORS.append(f"{path}: city page needs 'city'")
            return None
        meta["city_slug"] = slugify(meta["city"])
    if scope == "national":
        meta["url_path"] = f"/{meta['slug']}/"
        folder = "national"
    elif scope == "state":
        meta["url_path"] = f"/{meta['state_slug']}/{meta['slug']}/"
        folder = meta["state_slug"]
    else:
        meta["url_path"] = f"/{meta['city_slug']}/{meta['slug']}/"
        folder = meta["city_slug"]
    if path.parent.name != folder:
        ERRORS.append(f"{path}: should live in content/pages/{folder}/")
    if meta.get("slug") != path.stem:
        ERRORS.append(f"{path}: file name must equal slug '{meta.get('slug')}'")
    if meta.get("topic") in LEGAL_TOPICS and "{{legal-help}}" not in meta["body"]:
        ERRORS.append(f"{path}: topic '{meta['topic']}' must include the {{{{legal-help}}}} box")
    return meta


def affiliate_href(key):
    a = CONFIG["affiliates"].get(key)
    if not a:
        ERRORS.append(f"unknown affiliate '{key}'")
        return "#"
    return a.get("tracking_url") or a["url"]


def partner_box(page):
    def render():
        keys = page.get("partners")
        if keys is None:
            keys = list(CONFIG["affiliates"])
        for key in keys:
            if key not in CONFIG["affiliates"]:
                ERRORS.append(f"{page['_path'].name}: unknown partner '{key}'")
        keys = [k for k in keys if k in CONFIG["affiliates"]]
        if not keys:
            ERRORS.append(f"{page['_path'].name}: {{{{partner-box}}}} used but no partners listed")
        items = []
        for key in keys:
            a = CONFIG["affiliates"][key]
            items.append(
                f'<li><a class="btn" data-affiliate="{esc(key)}" href="{esc(affiliate_href(key))}" '
                f'rel="sponsored nofollow noopener" target="_blank">{esc(a["name"])} &rarr;</a>'
                f'<span>{esc(a["blurb"])}</span></li>')
        intro = page.get("partner_intro") or (
            "If you decide to move your things, compare a few options before you sign. Ask each place what the rent will be "
            "after any move-in special ends, and get it in writing.")
        return (
            '<aside class="pickup-box" aria-labelledby="partner-h">'
            f'<h2 id="partner-h">{esc(page.get("partner_heading", "Compare other storage options"))}</h2>'
            f'<p>{esc(intro)}</p>'
            f'<ul>{"".join(items)}</ul>'
            '<p class="small"><strong>Paid partner link.</strong> We may earn a commission if you rent through these links, at no extra cost to you. '
            'Partners never change what our guides say. <a href="/disclosure/">Disclosure</a></p>'
            '</aside>')
    return render


def legal_links_for(state):
    """National links (ABA only where the state participates) + the state's own links."""
    links = []
    st = LEGAL["states"].get(state) if state else None
    if state and st is None:
        ERRORS.append(f"state {state} has no legal_help entry in site.config.json")
    for l in LEGAL["national"]:
        if l.get("aba") and state and not (st or {}).get("aba_free_legal_answers"):
            continue
        links.append(l)
    return ((st or {}).get("links", []) if state else []) + links


def legal_box(page):
    def render():
        state = page.get("state") if page.get("scope") != "national" else None
        lis = "".join(f'<li><a href="{esc(l["url"])}" rel="noopener">{esc(l["name"])}</a>: {esc(l["blurb"])}</li>'
                      for l in legal_links_for(state))
        where = f" in {esc(STATES[state])}" if state else ""
        return (
            '<aside class="legal-box" aria-labelledby="legal-h">'
            f'<h2 id="legal-h">Free legal help{where}</h2>'
            '<p>If a sale date is close, or you think the facility skipped a required step, talk to a lawyer quickly. '
            'These are free or low-cost legal aid and pro bono services, <strong>not paid partners</strong>. '
            'We earn nothing from them. Most have income limits.</p>'
            f'<ul>{lis}</ul>'
            '<p class="small">More options for every state: <a href="/free-legal-help/">Free legal help</a>.</p>'
            '</aside>')
    return render


def page_html(*, title, description, path, body, jsonld=None, extra_head=""):
    canonical = BASE + path
    ld = ""
    for block in (jsonld or []):
        ld += '<script type="application/ld+json">' + json.dumps(block, ensure_ascii=False).replace("</", "<\\/") + "</script>\n"
    out = TEMPLATE
    repl = {
        "{{lang}}": esc(CONFIG.get("language", "en-US")),
        "{{title}}": esc(title),
        "{{description}}": esc(description),
        "{{canonical}}": esc(canonical),
        "{{site_name}}": esc(CONFIG["site_name"]),
        "{{tagline}}": esc(CONFIG["tagline"]),
        "{{jsonld}}": ld,
        "{{extra_head}}": extra_head,
        "{{body}}": body,
        "{{year}}": str(dt.date.today().year),
        "{{contact_link}}": (f' &middot; <a href="mailto:{esc(CONFIG["contact_email"])}">Contact</a>'
                             if CONFIG.get("contact_email") else ""),
    }
    for k, v in repl.items():
        out = out.replace(k, v)
    return out


def write(path, content):
    f = OUT / path.lstrip("/")
    if path.endswith("/"):
        f = f / "index.html"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(with_base(content))


def fmt_date(iso):
    d = dt.date.fromisoformat(iso)
    return d.strftime("%b %-d, %Y")


def crumb_trail(p):
    trail = [("Home", "/")]
    if p["scope"] in ("state", "city"):
        trail.append((p["state_name"], f"/{p['state_slug']}/"))
    if p["scope"] == "city":
        trail.append((f'{p["city"]}, {p["state"]}', f"/{p['city_slug']}/"))
    trail.append((p["label"], p["url_path"]))
    return trail


def render_page(p, all_pages):
    sources = {}
    for i, s in enumerate(p["sources"], 1):
        s = dict(s)
        for k in ("id", "publisher", "title", "url"):
            if not s.get(k):
                ERRORS.append(f"{p['_path'].name}: source #{i} missing '{k}'")
        s["_n"] = i
        s["_checked"] = fmt_date(s.get("checked", p["last_checked"]))
        sources[s["id"]] = s
    used, toc = set(), []
    has_aff = "{{partner-box}}" in p["body"]
    shortcodes = {"partner-box": partner_box(p), "legal-help": legal_box(p)}
    body_html = markdown(p["body"], sources, used, shortcodes, toc)

    facts = ""
    if p.get("quick_facts"):
        lis = "".join(f"<li>{inline(f, sources, used)}</li>" for f in p["quick_facts"])
        facts = f'<section class="facts" aria-label="Quick facts"><h2>Quick answer</h2><ul>{lis}</ul></section>'

    faq_html, faq_ld = "", None
    if p.get("faq"):
        toc.append(("faq", "FAQ"))
        qa = []
        for f in p["faq"]:
            qa.append(f'<details><summary>{esc(f["q"])}</summary><div>{inline(f["a"], sources, used)}</div></details>')
        faq_html = '<section class="faq"><h2 id="faq">Frequently asked questions</h2>' + "".join(qa) + "</section>"
        faq_ld = {
            "@context": "https://schema.org", "@type": "FAQPage",
            "mainEntity": [{"@type": "Question", "name": f["q"],
                            "acceptedAnswer": {"@type": "Answer",
                                               "text": re.sub(r"<[^>]+>", "", inline(f["a"], sources)).replace("&amp;", "&")}}
                           for f in p["faq"]]}

    for sid in sources:
        if sid not in used:
            ERRORS.append(f"{p['_path'].name}: source '{sid}' is listed but never cited")
    toc.append(("sources", "Sources"))
    src_lis = "".join(
        f'<li id="src-{s["_n"]}"><a href="{esc(s["url"])}" rel="noopener">{esc(s["title"])}</a> '
        f'&mdash; {esc(s["publisher"])}. <span class="checked">Last checked {esc(s["_checked"])}.</span></li>'
        for s in sources.values())
    sources_html = (f'<section class="sources"><h2 id="sources">Sources</h2>'
                    f'<p class="small">{esc(p.get("sources_note", SOURCES_NOTE))}</p><ol>{src_lis}</ol></section>')

    def is_related(o):
        if o is p:
            return False
        if o["topic"] == p["topic"]:
            return True
        if p["scope"] != "national" and o["scope"] != "national" and o["state"] == p["state"]:
            return True
        return o["scope"] == "national" or p["scope"] == "national"
    related = [o for o in all_pages if is_related(o)]
    rel_html = ""
    if related:
        rel_html = '<section class="related"><h2>Related guides</h2><ul>' + "".join(
            f'<li><a href="{o["url_path"]}">{esc(o["title"])}</a></li>' for o in related) + "</ul></section>"

    toc_items = []
    for hid, t in toc:
        label = inline(re.sub(r"\[\[.*?\]\]", "", t)).strip()
        toc_items.append(f'<li><a href="#{hid}">{label}</a></li>')
    toc_html = ('<nav class="toc" aria-label="On this page"><strong>On this page</strong><ul>'
                + "".join(toc_items) + "</ul></nav>")

    disclosure = ('<p class="disclosure"><strong>Disclosure:</strong> This page contains paid partner links to storage marketplaces. '
                  'If you rent through them we may earn a commission, at no extra cost to you. It never affects the rules we report, '
                  'which come only from statutes and official sources. Legal aid links are never paid. <a href="/disclosure/">Learn more</a>.</p>') if has_aff else ""
    not_advice = ('<p class="small">This is general legal information, not legal advice. We are not lawyers. '
                  'Check the linked law and talk to a lawyer or <a href="/free-legal-help/">free legal aid</a> about your situation.</p>')

    trail = crumb_trail(p)
    crumbs = ('<nav class="crumbs" aria-label="Breadcrumb">' + " &rsaquo; ".join(
        f'<a href="{u}">{esc(n)}</a>' for n, u in trail[:-1]) + f' &rsaquo; <span>{esc(trail[-1][0])}</span></nav>')

    body = f"""{crumbs}
<article>
<header class="page-head">
<h1>{esc(p["title"])}</h1>
<p class="lede">{esc(p["description"])}</p>
<p class="meta">Last checked against official sources: <time datetime="{p["last_checked"]}">{fmt_date(p["last_checked"])}</time> &middot; Updated <time datetime="{p["updated"]}">{fmt_date(p["updated"])}</time></p>
{disclosure}
{not_advice}
</header>
{facts}
{toc_html}
{body_html}
{faq_html}
{sources_html}
</article>
{rel_html}"""

    about = ({"@type": "State", "name": p["state_name"]} if p["scope"] == "state" else
             {"@type": "City", "name": f'{p["city"]}, {p["state"]}'} if p["scope"] == "city" else
             {"@type": "Country", "name": "United States"})
    article_ld = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": p["title"], "description": p["description"],
        "datePublished": p["published"], "dateModified": p["updated"],
        "mainEntityOfPage": BASE + p["url_path"],
        "author": {"@type": "Organization", "name": CONFIG["site_name"], "url": BASE + "/about/"},
        "publisher": {"@type": "Organization", "name": CONFIG["site_name"], "url": BASE + "/"},
        "about": about,
        "citation": [s["url"] for s in sources.values()],
    }
    crumbs_ld = {
        "@context": "https://schema.org", "@type": "BreadcrumbList",
        "itemListElement": [{"@type": "ListItem", "position": i, "name": n, "item": BASE + u}
                            for i, (n, u) in enumerate(trail, 1)]}
    lds = [article_ld, crumbs_ld] + ([faq_ld] if faq_ld else [])
    write(p["url_path"], page_html(title=p.get("seo_title", p["title"]), description=p["description"],
                                   path=p["url_path"], body=body, jsonld=lds))


def render_static_page(path, src_file, title, description):
    md = (ROOT / "content" / src_file).read_text()
    md = md.replace("{{site_name}}", CONFIG["site_name"])
    contact = CONFIG.get("contact_email")
    md = md.replace("{{contact}}", f"Spotted an error? Email [{contact}](mailto:{contact})." if contact else
                    "Spotted an error? A corrections address is coming soon.")
    body = f'<article><header class="page-head"><h1>{esc(title)}</h1></header>{markdown(md)}</article>'
    write(path, page_html(title=f"{title} | {CONFIG['site_name']}", description=description, path=path, body=body))


def render_legal_page():
    def lis(links):
        return "".join(f'<li><a href="{esc(l["url"])}" rel="noopener">{esc(l["name"])}</a>: {esc(l["blurb"])}</li>' for l in links)
    aba_states = [STATES[c] for c, s in sorted(LEGAL["states"].items()) if s.get("aba_free_legal_answers")]
    no_aba = [STATES[c] for c, s in sorted(LEGAL["states"].items()) if not s.get("aba_free_legal_answers")]
    states_html = ""
    for code, s in sorted(LEGAL["states"].items(), key=lambda kv: STATES[kv[0]]):
        if not s.get("links"):
            continue
        states_html += f'<h3 id="{state_slug(code)}">{esc(STATES[code])}</h3><ul>{lis(s["links"])}</ul>'
    aba_note = ""
    if no_aba:
        aba_note = (f'<p class="note">ABA Free Legal Answers was not open in {esc(", ".join(no_aba))} when we last checked '
                    f'its participating-state list. Use the state links below instead.</p>')
    body = f"""<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a> &rsaquo; <span>Free legal help</span></nav>
<article><header class="page-head"><h1>Free and low-cost legal help for storage renters</h1>
<p class="lede">If your storage unit is headed to a lien sale or auction, or you think the facility broke the rules, these free legal aid and pro bono services can help. Most have income limits.</p>
<p class="meta">Every link checked <time datetime="{LEGAL["checked"]}">{fmt_date(LEGAL["checked"])}</time>.</p>
<p class="disclosure"><strong>Not paid partners.</strong> These are nonprofit legal aid, court and bar association services. We earn nothing from them and they don't pay us.</p></header>
<h2 id="national">Anywhere in the U.S.</h2><ul>{lis(LEGAL["national"])}</ul>
{aba_note}
<h2 id="by-state">By state</h2>
{states_html}
<h2 id="what-to-bring">What to have ready when you call</h2>
<ul><li>Your storage rental agreement (lease), including any addendum.</li>
<li>Every notice the facility sent you, and the envelope or email it came in (the date matters).</li>
<li>Your payment history and the amount the facility says you owe.</li>
<li>The sale date, time and place or website, if the notice lists one.</li></ul>
<p class="small">This page is general information, not legal advice. Legal aid offices decide who they can help.</p>
</article>"""
    write("/free-legal-help/", page_html(
        title=f"Free Legal Help for Storage Unit Renters (Legal Aid & Pro Bono) | {CONFIG['site_name']}",
        description="Free legal aid and pro bono lawyers for storage unit renters facing a lien sale or auction, nationwide and by state. Not paid partners.",
        path="/free-legal-help/", body=body))


def hub_list(qs):
    return "".join(f'<li><a href="{q["url_path"]}">{esc(q["title"])}</a> <span class="small">Checked {fmt_date(q["last_checked"])}</span></li>' for q in qs)


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    pages = [p for p in (load_page(f) for f in sorted((ROOT / "content" / "pages").glob("*/*.md"))) if p]
    seen = {}
    for p in pages:
        for k in ("title", "description", "url_path"):
            if p[k] in seen:
                ERRORS.append(f"duplicate {k}: {p[k]!r}")
            seen[p[k]] = 1
    for p in pages:
        render_page(p, pages)

    national = [p for p in pages if p["scope"] == "national"]
    states = {}
    for p in pages:
        if p["scope"] != "national":
            states.setdefault(p["state"], []).append(p)
    cities = {}
    for p in pages:
        if p["scope"] == "city":
            cities.setdefault((p["city"], p["state"], p["city_slug"]), []).append(p)

    hub_slugs = {state_slug(c) for c in states} | {c[2] for c in cities}
    for p in national:
        if p["slug"] in hub_slugs:
            ERRORS.append(f"national slug '{p['slug']}' collides with a state/city hub")
    if {state_slug(c) for c in states} & {c[2] for c in cities}:
        ERRORS.append("a city slug equals a state slug; rename the city (e.g. 'New York City')")
    if hub_slugs & RESERVED:
        ERRORS.append(f"hub slug uses a reserved path: {hub_slugs & RESERVED}")

    # state hubs
    for code, plist in sorted(states.items(), key=lambda kv: STATES[kv[0]]):
        name, sslug = STATES[code], state_slug(code)
        st_pages = [q for q in plist if q["scope"] == "state"]
        city_html = ""
        for (city, st, cslug), cps in sorted(cities.items()):
            if st == code:
                city_html += f'<h3><a href="/{cslug}/">{esc(city)}</a></h3><ul class="guide-list">{hub_list(cps)}</ul>'
        body = (f'<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a> &rsaquo; <span>{esc(name)}</span></nav>'
                f'<article><header class="page-head"><h1>{esc(name)} self-storage renter rules</h1>'
                f'<p class="lede">What {esc(name)} law says about storage unit late fees, lien sales and auctions, and how to stop a sale, '
                f'from the statute text with links.</p></header>'
                f'<h2 id="state-guides">Statewide guides</h2><ul class="guide-list">{hub_list(st_pages) or "<li>Coming soon.</li>"}</ul>'
                + (f'<h2 id="cities">Cities</h2>{city_html}' if city_html else "")
                + f'<h2 id="everywhere">Guides for every state</h2><ul class="guide-list">{hub_list(national)}'
                f'<li><a href="/free-legal-help/#{sslug}">Free legal help in {esc(name)}</a></li></ul></article>')
        write(f"/{sslug}/", page_html(
            title=f"{name} Storage Unit Laws: Late Fees, Lien Sales & Auctions | {CONFIG['site_name']}",
            description=f"{name} self-storage renter rules from the statute: late fees, lien sale notices, auction timelines, and how to stop a sale.",
            path=f"/{sslug}/", body=body))

    # city hubs
    for (city, st, cslug), plist in sorted(cities.items()):
        body = (f'<nav class="crumbs" aria-label="Breadcrumb"><a href="/">Home</a> &rsaquo; <a href="/{state_slug(st)}/">{esc(STATES[st])}</a> '
                f'&rsaquo; <span>{esc(city)}, {esc(st)}</span></nav>'
                f'<article><header class="page-head"><h1>Self-storage in {esc(city)}, {esc(st)}: renter guides</h1>'
                f'<p class="lede">Local guides for storage renters in {esc(city)}, plus the {esc(STATES[st])} rules that apply to every unit there.</p></header>'
                f'<ul class="guide-list">{hub_list(plist)}{hub_list([q for q in states[st] if q["scope"] == "state"])}</ul></article>')
        write(f"/{cslug}/", page_html(
            title=f"{city}, {st} Self-Storage Renter Guides | {CONFIG['site_name']}",
            description=f"Storage unit renter guides for {city}, {st}: cutting storage costs, avoiding rent hikes, and {STATES[st]} lien and auction rules.",
            path=f"/{cslug}/", body=body))

    # homepage
    groups = ""
    for code, plist in sorted(states.items(), key=lambda kv: STATES[kv[0]]):
        lis = "".join(f'<li><a href="{q["url_path"]}">{esc(q["label"])}' + (f' ({esc(q["city"])})' if q["scope"] == "city" else "") + '</a></li>' for q in plist)
        groups += f'<section class="city"><h3><a href="/{state_slug(code)}/">{esc(STATES[code])}</a></h3><ul>{lis}</ul></section>'
    latest = sorted(pages, key=lambda q: q["published"], reverse=True)[:10]
    home_body = f"""<section class="hero"><h1>{esc(CONFIG["site_name"])}</h1>
<p class="lede">{esc(CONFIG["tagline"])} Every rule comes from the statute text or an official page, linked, with the date we last checked it.</p></section>
<section><h2>Start here</h2><ul class="guide-list">{hub_list(national)}<li><a href="/free-legal-help/">Free legal help for storage renters</a> <span class="small">Legal aid and pro bono, not paid partners</span></li></ul></section>
<section><h2>Latest guides</h2><ul class="guide-list">{hub_list(latest)}</ul></section>
<section><h2>All states</h2><div class="cities">{groups}</div>
<p class="small">New states and cities are added regularly.</p></section>"""
    site_ld = {"@context": "https://schema.org", "@type": "WebSite", "name": CONFIG["site_name"], "url": BASE + "/",
               "description": CONFIG["tagline"]}
    write("/", page_html(title=f"{CONFIG['site_name']}: Storage Unit Rent Increases, Late Fees & Auction Rules by State",
                         description="Storage rent went up or your unit is headed to auction? Plain-English renter rules by state, from the statutes, with free legal help links.",
                         path="/", body=home_body, jsonld=[site_ld]))

    render_static_page("/about/", "about.md", "About " + CONFIG["site_name"],
                       f"Who runs {CONFIG['site_name']}, how we research self-storage laws, and how we make money.")
    render_static_page("/disclosure/", "disclosure.md", "Disclosure & Privacy",
                       f"How {CONFIG['site_name']} earns money from paid partner links, and our privacy policy: no tracking, no cookies.")
    render_legal_page()

    write("/404.html", page_html(title=f"Page not found | {CONFIG['site_name']}", description="Page not found.",
                                 path="/404.html", body='<article><h1>Page not found</h1><p><a href="/">Back to all states</a></p></article>',
                                 extra_head='<meta name="robots" content="noindex">'))

    last = max([p["updated"] for p in pages] or [dt.date.today().isoformat()])
    urls = [("/", last)]
    urls += [(f"/{state_slug(c)}/", max(q["updated"] for q in pl)) for c, pl in sorted(states.items())]
    urls += [(f"/{c[2]}/", max(q["updated"] for q in pl)) for c, pl in sorted(cities.items())]
    urls += [(p["url_path"], p["updated"]) for p in pages]
    urls += [("/free-legal-help/", LEGAL["checked"]), ("/about/", None), ("/disclosure/", None)]
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, lm in urls:
        sm.append(f"  <url><loc>{esc(BASE + u)}</loc>" + (f"<lastmod>{lm}</lastmod>" if lm else "") + "</url>")
    sm.append("</urlset>")
    (OUT / "sitemap.xml").write_text("\n".join(sm) + "\n")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n")

    for f in (ROOT / "static").iterdir():
        shutil.copy(f, OUT / f.name)
    (OUT / ".nojekyll").write_text("")

    if not BASE.endswith(BASE_PATH.rstrip("/")):
        print(f"WARNING: base_url ({BASE}) doesn't end with base_path ({BASE_PATH}); canonicals and links may disagree.")
    if ERRORS:
        print("BUILD ERRORS:\n  " + "\n  ".join(ERRORS))
        sys.exit(1)
    print(f"Built {len(pages)} guide page(s), {len(states)} state hub(s), {len(cities)} city hub(s) -> {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
