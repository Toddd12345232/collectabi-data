"""Pages from a-pt.co.jp, the company that makes the 記念きっぷ."""
import hashlib
import html as htmllib
import re
import unicodedata
from datetime import date, timedelta

from bs4 import BeautifulSoup

from regions import PREFS

SPECIALS_URL = "https://www.a-pt.co.jp/%E7%89%B9%E5%88%A5%E8%A8%98%E5%BF%B5%E3%81%8D%E3%81%A3%E3%81%B7-%E9%85%8D%E5%B8%83%E6%96%B9%E6%B3%95/"
NOTICES_URL = "https://www.a-pt.co.jp/%E9%81%93%E3%81%AE%E9%A7%85-%E3%81%9D%E3%81%AE%E4%BB%96%E6%83%85%E5%A0%B1/"

FIELDS = {"都道府県": "pref", "道の駅名": "station", "きっぷ名": "name", "配布日時": "when",
          "配布条件": "cond", "配付条件": "cond", "配布上限": "limit", "配付上限": "limit",
          "郵送依頼": "mail", "電話問合": "phone"}


def lines(page):
    """Visible text, one line per block element, spaces collapsed."""
    s = re.sub(r"(?is)<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", page)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|h[1-6]|li|tr|td|th)>", "\n", s)
    s = htmllib.unescape(re.sub(r"<[^>]+>", " ", s))
    out = []
    for line in s.split("\n"):
        line = re.sub(r"[ \t　\xa0]+", " ", line).strip()
        if line:
            out.append(line)
    return out


def classify_status(raw):
    r = raw.strip()
    if "閉館" in r or r.startswith("販売中止") or ("をもって" in r and ("中止" in r or "終了" in r)):
        return "stopped"
    if r.startswith("販売中") or ("販売中" in r and "販売中止" not in r):
        return "selling"
    if "抹消" in r:
        return "delisted"
    if any(w in r for w in ("中止", "終了", "拒否")):
        return "stopped"
    if "休止" in r:
        return "paused"
    if "未販売" in r:
        return "not_sold"
    if "開始" in r or "再開" in r or r.endswith(("～", "〜", "~")):
        return "selling"
    return "unknown"


def parse_status_page(page):
    rows = []
    for tr in BeautifulSoup(page, "html.parser").select("table tr"):
        tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(tds) >= 3 and re.fullmatch(r"\d{1,3}", tds[0]):
            rows.append({"no": tds[0], "name": tds[1], "raw": tds[2], "status": classify_status(tds[2])})
    return rows


def _dated(m, d, after):
    """The date M/D on or after about two months before `after`."""
    try:
        cand = date(after.year, m, d)
    except ValueError:
        return None
    if cand < after - timedelta(days=60):
        cand = cand.replace(year=cand.year + 1)
    return cand


def infer_dates(when, posted):
    t = unicodedata.normalize("NFKC", when or "")
    posted_d = date.fromisoformat(posted)
    m = re.search(r"(\d{1,2})\s*(?:/|月)\s*(\d{1,2})\s*日?", t)
    if not m:
        return None, None
    start = _dated(int(m[1]), int(m[2]), posted_d)
    if start is None:
        return None, None
    end = None
    e = re.match(r"\s*(?:\([^)]{1,3}\))?\s*[〜~-]\s*(?:(\d{1,2})\s*(?:/|月))?\s*(\d{1,2})\s*日?(?![\d:時])", t[m.end():])
    if e:
        end = _dated(int(e[1] or start.month), int(e[2]), start)
    elif "のみ" in t:
        end = start
    return start.isoformat(), end.isoformat() if end else None


_POST = re.compile(r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*・?\s*UP")
_ENDED = re.compile(r"道の駅\s*(.+?)\s*[｣」]\s*様は配布終了.*?(\d{4})年\s*(\d{1,2})\s*/\s*(\d{1,2})")
_FIELD = re.compile(r"^【\s*([^】]+?)\s*】\s*(.*)$")


def parse_specials(page):
    posts, cur = [], None
    for line in lines(page):
        m = _POST.match(line)
        if m:
            cur = {"posted": f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}", "pref": None, "station": None, "name": None,
                   "when": None, "cond": None, "limit": None, "mail": None, "phone": None, "extra": []}
            posts.append(cur)
            continue
        if cur is None or _ENDED.search(line):
            continue
        f = _FIELD.match(line)
        key = FIELDS.get(re.sub(r"\s", "", f[1])) if f else None
        if key and cur[key] is None:
            cur[key] = f[2].strip()
        else:
            cur["extra"].append(line)
    # The id must not change when a-pt edits a post's wording or dates, because ticks refer to it.
    # Posts for the same station on the same day are numbered from the oldest, so a new post
    # landing on top of the page doesn't renumber the older ones.
    seen = {}
    for p in reversed(posts):
        key = "|".join(str(p[k]) for k in ("posted", "pref", "station"))
        seen[key] = seen.get(key, 0) + 1
        p["id"] = hashlib.sha1(f"{key}|{seen[key]}".encode("utf-8")).hexdigest()[:10]
    for p in posts:
        p["start"], p["end"] = infer_dates(p["when"], p["posted"])
        p["ended"] = None
    return posts


def parse_ended(page):
    return [(m[1].strip(), f"{m[2]}-{int(m[3]):02d}-{int(m[4]):02d}")
            for line in lines(page) for m in [_ENDED.search(line)] if m]


_NOTICE_HEAD = re.compile(r"^(\S+?[都道府県])\s*[｢「](.+?)[｣」]")
_NOTICE_DATE = re.compile(r"(\d{4})年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*現在")


def parse_notices(page):
    out, head, text = [], None, []
    for line in lines(page):
        line = unicodedata.normalize("NFKC", line)
        m = _NOTICE_HEAD.match(line)
        if m and m[1] in PREFS:
            head, text = {"pref": m[1], "station": m[2].strip()}, []
            continue
        bare = next((p for p in PREFS if line.startswith(p)), None)
        if bare and len(line) <= 20 and not re.search(r"[｢「]", line):
            head, text = {"pref": bare, "station": None}, []
            continue
        d = _NOTICE_DATE.search(line)
        if d and head:
            if text:
                out.append({**head, "date": f"{d[1]}-{int(d[2]):02d}-{int(d[3]):02d}", "text": "\n".join(text)})
            text = []
            continue
        if head:
            text.append(line)
    return out
