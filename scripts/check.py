#!/usr/bin/env python3
"""Local QA for the built site. Standard library only.

  python3 scripts/check.py              # serve docs/ on a local port, crawl and validate
  python3 scripts/check.py --external   # also check that every external link answers (HEAD/GET)

Checks: every page returns 200; HTML tags balance; exactly one <h1>; unique <title> and meta
description; canonical tag; JSON-LD parses; internal links and #anchors resolve; sitemap URLs exist;
affiliate links carry data-affiliate + rel="sponsored", are labeled "Paid partner link" and the page shows a disclosure;
guide pages have Article JSON-LD and a non-empty Sources list; legal-help boxes contain no paid links.
"""
import functools
import http.server
import json
import sys
import threading
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "site.config.json").read_text())
DOCS = ROOT / CONFIG.get("output_dir", "docs")
BASE_PATH = "/" + CONFIG.get("base_path", "/").strip("/") + "/"
if BASE_PATH == "//":
    BASE_PATH = "/"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.links, self.ids = [], [], [], set()
        self.title, self.desc, self.canonical, self.h1 = None, None, None, 0
        self.jsonld, self._in_ld, self._in_title, self._buf = [], False, False, ""
        self.affiliate_links, self.text = [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "id" in a:
            if a["id"] in self.ids:
                self.errors.append(f"duplicate id {a['id']}")
            self.ids.add(a["id"])
        if tag not in VOID:
            self.stack.append(tag)
        if tag == "a" and a.get("href"):
            self.links.append(a["href"])
            if "data-affiliate" in a:
                self.affiliate_links.append(a)
        if tag == "link" and a.get("rel") == "canonical":
            self.canonical = a.get("href")
        if tag == "meta" and a.get("name") == "description":
            self.desc = a.get("content")
        if tag == "h1":
            self.h1 += 1
        if tag == "title":
            self._in_title, self._buf = True, ""
        if tag == "script" and a.get("type") == "application/ld+json":
            self._in_ld, self._buf = True, ""

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()
        if tag == "title":
            self.title, self._in_title = self._buf.strip(), False
        if tag == "script" and self._in_ld:
            self._in_ld = False
            try:
                self.jsonld.append(json.loads(self._buf))
            except Exception as e:
                self.errors.append(f"bad JSON-LD: {e}")

    def handle_data(self, d):
        if self._in_title or self._in_ld:
            self._buf += d
        else:
            self.text.append(d)


def fetch(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "Mozilla/5.0 (site-check)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as e:
        return 0, str(e)


def main():
    external = "--external" in sys.argv
    class Quiet(http.server.SimpleHTTPRequestHandler):
        """Serves docs/ only under BASE_PATH, like GitHub Pages does for a project site."""
        def log_message(self, *a):
            pass

        def translate_path(self, path):
            p = path.split("?", 1)[0].split("#", 1)[0]
            if not (p + "/").startswith(BASE_PATH):
                return str(DOCS / "__outside_base_path__")
            return super().translate_path("/" + p[len(BASE_PATH):])
    handler = functools.partial(Quiet, directory=str(DOCS))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    print(f"Serving {DOCS} at {origin}")

    problems, pages, todo, seen, ext = [], {}, [BASE_PATH + x for x in ("", "style.css", "favicon.svg", "404.html")], set(), set()
    print(f"Site root: {origin}{BASE_PATH}")
    if BASE_PATH != "/" and fetch(origin + "/")[0] == 200:
        problems.append("server answers outside base_path (test harness problem)")
    status, sm = fetch(origin + BASE_PATH + "sitemap.xml")
    if status != 200:
        problems.append("sitemap.xml missing")
    import re
    base = CONFIG["base_url"].rstrip("/")
    for loc in re.findall(r"<loc>(.*?)</loc>", sm):
        if not loc.startswith(base + "/"):
            problems.append(f"sitemap URL not under base_url: {loc}")
        todo.append(BASE_PATH + loc[len(base) + 1:])
    if fetch(origin + BASE_PATH + "robots.txt")[0] != 200:
        problems.append("robots.txt missing")

    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        status, body = fetch(origin + path)
        if status != 200:
            problems.append(f"{path}: HTTP {status}")
            continue
        if not path.endswith("/") and not path.endswith(".html"):
            continue
        p = Page()
        p.feed(body)
        pages[path] = p
        for e in p.errors:
            problems.append(f"{path}: {e}")
        if p.stack:
            problems.append(f"{path}: unclosed tags {p.stack}")
        if p.h1 != 1:
            problems.append(f"{path}: {p.h1} <h1> tags")
        if not p.title:
            problems.append(f"{path}: no <title>")
        if not p.desc:
            problems.append(f"{path}: no meta description")
        if not p.canonical:
            problems.append(f"{path}: no canonical")
        elif not path.endswith("404.html") and p.canonical != base + "/" + path[len(BASE_PATH):]:
            problems.append(f"{path}: canonical {p.canonical} doesn't match served URL")
        for href in p.links:
            u = urlparse(href)
            if u.scheme in ("http", "https"):
                ext.add(href.split("#")[0])
                continue
            if u.scheme == "mailto":
                continue
            target = urljoin(path, href)
            tpath, _, frag = target.partition("#")
            tpath = tpath or path
            if frag:
                todo.append(tpath)
                pages.setdefault("_anchors", []).append((path, tpath, frag))
            if tpath not in seen:
                todo.append(tpath)
        if p.affiliate_links:
            for a in p.affiliate_links:
                if "sponsored" not in a.get("rel", ""):
                    problems.append(f"{path}: affiliate link without rel=sponsored: {a.get('href')}")
            if "Disclosure:" not in "".join(p.text):
                problems.append(f"{path}: has affiliate links but no disclosure")
            if "Paid partner link" not in "".join(p.text):
                problems.append(f"{path}: affiliate links not labeled 'Paid partner link'")
        types = [j.get("@type") for j in p.jsonld]
        if 'id="sources"' in body:
            if "Article" not in types:
                problems.append(f"{path}: guide page missing Article JSON-LD")
            if '<li id="src-1">' not in body:
                problems.append(f"{path}: guide page has an empty Sources list")
        if "google-site-verification" in body:
            problems.append(f"{path}: contains a google-site-verification tag (Curbside Rules' tag must not be copied)")
        if 'class="legal-box"' in body:
            box = body.split('class="legal-box"', 1)[1].split("</aside>", 1)[0]
            if "sponsored" in box or "data-affiliate" in box:
                problems.append(f"{path}: legal-help box contains a paid/affiliate link")
        if "<details>" in body and "FAQPage" not in types:
            problems.append(f"{path}: FAQ present but no FAQPage JSON-LD")

    for src, tpath, frag in pages.pop("_anchors", []):
        tp = pages.get(tpath)
        if tp and frag not in tp.ids:
            problems.append(f"{src}: broken anchor {tpath}#{frag}")

    titles, descs = {}, {}
    for path, p in pages.items():
        if p.title in titles:
            problems.append(f"duplicate title on {path} and {titles[p.title]}")
        titles[p.title] = path
        if p.desc in descs:
            problems.append(f"duplicate description on {path} and {descs[p.desc]}")
        descs[p.desc] = path

    if external:
        print(f"Checking {len(ext)} external links...")
        for url in sorted(ext):
            s, _ = fetch(url, "HEAD")
            if s in (0, 403, 405, 404):
                s, _ = fetch(url)
            flag = "OK " if 200 <= s < 400 else ("WARN" if s in (401, 403, 429) else "ERR")
            if flag == "ERR" and url in CONFIG.get("external_links_verified_manually", {}):
                flag = "WARN"
                print(f"  WARN {s} {url}  (blocks scripts; verified manually: {CONFIG['external_links_verified_manually'][url]})")
                continue
            print(f"  {flag} {s} {url}" + ("  (site blocks bots; open it in a browser to confirm)" if flag == "WARN" else ""))
            if flag == "ERR":
                problems.append(f"external link {url}: HTTP {s}")

    srv.shutdown()
    print(f"Crawled {len(pages)} HTML pages, {len(ext)} unique external links.")
    if problems:
        print("PROBLEMS:\n  " + "\n  ".join(problems))
        sys.exit(1)
    print("All checks passed.")


if __name__ == "__main__":
    main()
