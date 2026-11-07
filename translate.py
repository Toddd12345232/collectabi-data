"""Translate special-ticket posts from Japanese into English, Traditional Chinese and Korean.

Uses the free MyMemory service (no account, 5,000 characters a day). DeepL was considered and
dropped on 25 Oct 2026: it is no longer free (a one-time 1,000,000-character credit, then paid).
Each post is translated once; the result is kept in state.json with a fingerprint of
the Japanese, so a post a-pt edits is translated again.
"""
import hashlib
import html
import json
import re
from datetime import timedelta

import requests

TARGETS = ("en", "zh-Hant", "ko")
FIELDS = ("name", "when", "cond", "limit", "mail", "phone")
WINDOW_DAYS = 180          # older posts are history: left in Japanese
MYMEMORY_DAILY = 4500      # 5,000 a day without an account
CHUNK = 160                # MyMemory takes up to 500 bytes a request


class TranslateError(Exception):
    pass


def chunks(text, size=CHUNK):
    """Split text into pieces of at most `size` characters, at line ends and 。 where possible."""
    out = []
    for line in text.split("\n"):
        while len(line) > size:
            cut = line.rfind("。", 0, size)
            cut = cut + 1 if cut > 0 else size
            out.append(line[:cut])
            line = line[cut:]
        if line:
            out.append(line)
    return out


class MyMemory:
    name = "MyMemory"
    budget = MYMEMORY_DAILY
    LANG = {"en": "en-GB", "zh-Hant": "zh-TW", "ko": "ko-KR"}

    def __init__(self, session=None):
        self.session = session or requests.Session()

    def _one(self, text, target):
        r = self.session.get("https://api.mymemory.translated.net/get",
                             params={"q": text, "langpair": f"ja|{self.LANG[target]}"}, timeout=30)
        try:
            d = r.json()
        except ValueError as e:
            raise TranslateError(f"MyMemory: HTTP {r.status_code}") from e
        out = html.unescape((d.get("responseData") or {}).get("translatedText") or "")
        if d.get("responseStatus") not in (200, "200") or "MYMEMORY WARNING" in out or d.get("quotaFinished"):
            raise TranslateError(f"MyMemory: {d.get('responseDetails') or out or d.get('responseStatus')}")
        return out

    def translate(self, texts, target):
        return ["\n".join(self._one(c, target) for c in text.split("\n") if c) if text else ""
                for text in ["\n".join(chunks(t)) for t in texts]]


def backend_from_env():
    return MyMemory()


def source_texts(post):
    """The Japanese worth translating. Plain OK/NG for mail and phone is shown by the app itself."""
    out = {k: post.get(k) or "" for k in FIELDS}
    for k in ("mail", "phone"):
        if out[k].strip().upper() in ("OK", "NG", ""):
            out[k] = ""
    out["extra"] = "\n".join(post.get("extra") or [])
    return {k: v for k, v in out.items() if v.strip()}


def fingerprint(texts):
    return hashlib.sha1(json.dumps(texts, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _order(posts, today):
    """Posts on now or coming up first (soonest first), then the rest newest first; old ones skipped."""
    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    recent = (today - timedelta(days=2)).isoformat()
    today_s = today.isoformat()
    live = sorted((p for p in posts if not p.get("ended") and ((p.get("start") or "") >= recent or (p.get("end") or "") >= today_s)),
                  key=lambda p: p["start"])
    ids = {p["id"] for p in live}
    rest = sorted((p for p in posts if p["id"] not in ids and (p.get("start") or p.get("posted") or "") >= since),
                  key=lambda p: p.get("posted") or "", reverse=True)
    return live + rest


def translate_specials(posts, cache, today, translator, budget):
    """Returns (cache, characters used, notes). Never raises: a failing service just stops this run."""
    cache = dict(cache or {})
    used, notes = 0, []
    for p in _order(posts, today):
        texts = source_texts(p)
        key = fingerprint(texts)
        old = cache.get(p["id"])
        if old and old.get("key") == key and all(t in old for t in TARGETS):
            continue
        cost = sum(len(v) for v in texts.values()) * len(TARGETS)
        if used + cost > budget:
            notes.append(f"translation: daily allowance reached ({used} characters); the rest continues tomorrow")
            break
        fields = list(texts)
        entry = {"key": key}
        try:
            for target in TARGETS:
                got = translator.translate([texts[f] for f in fields], target)
                tr = dict(zip(fields, got))
                if "extra" in tr:
                    tr["extra"] = [x for x in tr["extra"].split("\n") if x.strip()]
                entry[target] = tr
        except (TranslateError, requests.RequestException, KeyError, ValueError) as e:
            notes.append(f"translation stopped: {e}")
            break
        cache[p["id"]] = entry
        used += cost
    return cache, used, notes
