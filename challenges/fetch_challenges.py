#!/usr/bin/env python3
"""Save every Junction challenge (main + tech) as a markdown file.

The challenge pages need a logged-in session, and Clerk session cookies only
last 60 seconds, so grab a fresh one right before running:

  1. Open https://hackjunction.app/participate/45/challenges while logged in.
  2. In the DevTools console run (refreshes the token, copies the cookies):
       await Clerk.session.getToken({skipCache: true}); copy(document.cookie)
  3. Within a minute:
       JUNCTION_COOKIE="$(pbpaste)" python3 challenges/fetch_challenges.py

Output: challenges/main/*.md, challenges/tech/*.md and challenges/README.md.
Any value from the repo's .env (passwords, API keys) that appears in a page is
written as $NAME instead, so the output is safe to push. Standard library only.
"""

import argparse
import base64
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://hackjunction.app"
KINDS = {  # API type -> (folder, URL segment, label, criteria key)
    "main": ("main", "challenges", "Main challenge", "challengeCriteria"),
    "side": ("tech", "tech-challenges", "Tech challenge", "sideChallengeCriteria"),
}


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_secrets(path=ENV_FILE):
    """{value: NAME} for every .env entry long enough to be a real secret."""
    secrets = {}
    if path.exists():
        for line in path.read_text().splitlines():
            name, sep, value = line.strip().partition("=")
            value = value.strip().strip("'\"")
            if sep and not name.startswith("#") and len(value) >= 8:
                secrets[value] = name.strip()
    return secrets


def redact(text, secrets):
    for value, name in secrets.items():
        text = text.replace(value, f"${name}")
    return text


SSL_CTX = ssl.create_default_context()
if os.path.exists("/etc/ssl/cert.pem"):  # python.org builds on macOS ship no CA certs
    SSL_CTX.load_verify_locations("/etc/ssl/cert.pem")


def fetch(path, cookie):
    req = urllib.request.Request(BASE + path, headers={
        "Cookie": cookie, "RSC": "1", "User-Agent": "Mozilla/5.0 (challenge-export)",
    })
    try:
        with urllib.request.urlopen(req, timeout=30, context=SSL_CTX) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} for {path}: the cookie is missing or expired "
                 "(they last 60 s). Copy a fresh one and rerun.")


def check_cookie(cookie):
    """Fail early, with a useful message, if the session token is absent or stale."""
    jar = dict(p.strip().split("=", 1) for p in cookie.split(";") if "=" in p)
    token = jar.get("__session")
    if not token:
        sys.exit("No __session cookie in JUNCTION_COOKIE. Run the console line on a "
                 "hackjunction.app page while logged in, then rerun.")
    try:
        part = token.split(".")[1]
        exp = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))["exp"]
    except (IndexError, ValueError, KeyError):
        return
    if exp - time.time() < 5:
        sys.exit(f"The session token expired {time.time() - exp:.0f} s ago. Run the "
                 "console line again and rerun within a minute.")


def parse_rsc(data):
    """Split a Next.js RSC payload into {row id: JSON value or text chunk}."""
    rows, i, n = {}, 0, len(data)
    while i < n:
        if data[i] == 0x0A:
            i += 1
            continue
        colon = data.index(b":", i)
        rid, j = data[i:colon].decode(), colon + 1
        if data[j:j + 1] == b"T":  # text chunk: T<hex byte length>,<text>
            comma = data.index(b",", j)
            end = comma + 1 + int(data[j + 1:comma], 16)
            rows[rid] = data[comma + 1:end].decode()
            i = end
            continue
        end = data.find(b"\n", j)
        end = n if end == -1 else end
        try:
            rows[rid] = json.loads(data[j:end])
        except ValueError:
            pass  # module imports, hints etc.
        i = end + 1
    return rows


def resolve(value, rows, depth=0):
    """Replace RSC references ($1b, $7:props:x, $$, $D...) with real values."""
    if depth > 50:
        return value
    if isinstance(value, list):
        return [resolve(v, rows, depth + 1) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, rows, depth + 1) for k, v in value.items()}
    if not isinstance(value, str) or not value.startswith("$"):
        return value
    if value.startswith("$$"):
        return value[1:]
    if value.startswith("$D"):
        return value[2:]
    if value == "$undefined":
        return None
    m = re.fullmatch(r"\$([0-9a-f]+)((?::[^:]+)*)", value)
    if not m or m.group(1) not in rows:
        return value
    target = rows[m.group(1)]
    for key in filter(None, m.group(2).split(":")):
        if isinstance(target, list):  # React element: ["$", type, key, props]
            target = target[3] if key == "props" else target[int(key)]
        else:
            target = target[key]
    return resolve(target, rows, depth + 1)


def find_props(rows, key):
    """Find the component props object that holds `key`."""
    stack = list(rows.values())
    while stack:
        x = stack.pop()
        if isinstance(x, dict):
            if key in x:
                return x
            stack.extend(x.values())
        elif isinstance(x, list):
            stack.extend(x)
    raise KeyError(f"{key!r} not found in page data (did the site change?)")


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:80]


def to_markdown(ch, criteria, org, url, label):
    meta = [f"**By:** {ch.get('sponsor') or org.get('name', '?')}",
            f"**Type:** {label}"]
    if ch.get("track"):
        meta.append(f"**Track:** {ch['track']['name']}")
    if ch.get("tags"):
        meta.append(f"**Tags:** {', '.join(ch['tags'])}")
    links = [f"**Page:** {url}"]
    if org.get("website"):
        links.append(f"**Website:** {org['website']}")
    lines = [f"# {ch['title']}", "", " · ".join(meta), "", " · ".join(links)]
    summary = (ch.get("summary") or "").strip()
    description = (ch.get("description") or "").strip()
    if summary and not summary.startswith("#") and summary not in description[:500]:
        lines += ["", f"> {summary}"]
    if description:
        lines += ["", description]
    if (ch.get("resources") or "").strip():
        lines += ["", "## Resources", "", ch["resources"].strip()]
    if criteria:
        lines += ["", "## Judging criteria", ""]
        for c in criteria:
            weight = f" ({c['weight']}%)" if c.get("weight") is not None else ""
            desc = f" – {c['description'].strip()}" if c.get("description") else ""
            lines.append(f"- **{c['name'].strip()}**{weight}{desc}")
    if ch.get("prizes"):
        lines += ["", "## Prizes", ""]
        for p in sorted(ch["prizes"], key=lambda p: p.get("priority", 0)):
            lines.append(f"- **{p['name']}:** {p['description'].strip()}")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--event", default="45", help="Junction event id (default 45)")
    ap.add_argument("--out", default=Path(__file__).resolve().parent, type=Path,
                    help="output folder (default: this script's folder)")
    ap.add_argument("--cookie", default=os.environ.get("JUNCTION_COOKIE"),
                    help="Cookie header (default: $JUNCTION_COOKIE)")
    args = ap.parse_args()
    if not args.cookie:
        sys.exit("Set JUNCTION_COOKIE (see the instructions at the top of this file).")
    check_cookie(args.cookie)

    listing = parse_rsc(fetch(f"/participate/{args.event}/challenges", args.cookie))
    challenges = resolve(find_props(listing, "challenges")["challenges"], listing)

    def fetch_one(ch):
        folder, segment, label, crit_key = KINDS[ch["type"]]
        path = f"/participate/{args.event}/{segment}/{ch['id']}"
        rows = parse_rsc(fetch(path, args.cookie))
        props = find_props(rows, crit_key)
        full = resolve(props.get("challenge") or props.get("sideChallenge"), rows)
        md = to_markdown(full, resolve(props[crit_key], rows),
                         resolve(props.get("organizationData") or {}, rows),
                         BASE + path, label)
        return ch["type"], full, f"{folder}/{slugify(full['title'])}.md", md

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(fetch_one, challenges))

    secrets = load_secrets()
    index = ["# Junction challenges", "",
             "Generated by `fetch_challenges.py`. Passwords and keys appear as `$NAME`;",
             "the real values are in the repo's `.env`, which is not committed.", ""]
    for kind, (folder, _, label, _) in KINDS.items():
        (args.out / folder).mkdir(parents=True, exist_ok=True)
        items = [r for r in results if r[0] == kind]
        index += [f"## {label}s ({len(items)})", "",
                  "| Challenge | By | Track | Top prize |", "|---|---|---|---|"]
        for _, ch, rel, md in sorted(items, key=lambda r: r[1]["title"].lower()):
            (args.out / rel).write_text(redact(md, secrets))
            prizes = ch.get("prizes") or [{}]
            top = next((p for p in prizes if "1st" in p.get("name", "")),
                       min(prizes, key=lambda p: p.get("priority", 0)))
            prize = (top.get("description") or "").replace("\n", " ").replace("|", "/")
            track = (ch.get("track") or {}).get("name", "")
            index.append(f"| [{ch['title']}]({rel}) | {ch.get('sponsor', '')} "
                         f"| {track} | {prize[:80]} |")
        index.append("")
    (args.out / "README.md").write_text(redact("\n".join(index), secrets))
    print(f"Wrote {len(results)} challenges to {args.out}")


if __name__ == "__main__":
    main()
