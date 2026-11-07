"""Turn michieki.jp opening-hours text into a schedule the app can check.

Only clear, common wording is read. Anything else gives None, so the app
shows the raw text without an Open/Closed badge rather than guess.
"""
import re
import unicodedata

TILDE = r"[〜~-]"
TIME = r"(\d{1,2}):(\d{2})"
RANGE = TIME + r"\s*" + TILDE + r"\s*" + TIME
DOW = {"日": 0, "月": 1, "火": 2, "水": 3, "木": 4, "金": 5, "土": 6}
NEW_YEAR = ["12-29", "01-03"]
# Words that say the hours change or come with conditions: don't trust the badge then.
UNSURE = ("季節", "変更", "時期", "冬期", "夏期", "※")


def _norm(text):
    return unicodedata.normalize("NFKC", text).replace("－", "-")


def _hm(h, m):
    h, m = int(h), int(m)
    if h > 24 or m > 59:
        raise ValueError
    return f"{h:02d}:{m:02d}"


def _months(a, b):
    a, b = int(a), int(b)
    if not (1 <= a <= 12 and 1 <= b <= 12):
        raise ValueError
    return list(range(a, b + 1)) if a <= b else list(range(a, 13)) + list(range(1, b + 1))


def _md(m, d):
    m, d = int(m), int(d)
    if not (1 <= m <= 12 and 1 <= d <= 31):
        raise ValueError
    return f"{m:02d}-{d:02d}"


def _season(inner, base):
    m = re.fullmatch(r"(\d{1,2})" + TILDE + r"(\d{1,2})月(?:は)?" + TIME + "まで", inner)
    if m:
        return {"months": _months(m[1], m[2]), "open": base["open"], "close": _hm(m[3], m[4])}
    m = re.fullmatch(r"(\d{1,2})" + TILDE + r"(\d{1,2})月(?:は)?" + RANGE, inner)
    if m:
        return {"months": _months(m[1], m[2]), "open": _hm(m[3], m[4]), "close": _hm(m[5], m[6])}
    return None


def parse_hours(text):
    if not text:
        return None
    t = _norm(text).strip()
    if any(w in t for w in UNSURE):
        return None
    m = re.match(RANGE, t)
    if not m:
        return None
    try:
        out = {"open": _hm(m[1], m[2]), "close": _hm(m[3], m[4]), "seasons": []}
        rest = t[m.end():].lstrip()
        if rest.startswith("("):
            end = rest.find(")")
            season = _season(rest[1:end], out) if end > 0 else None
            if season is None:
                return None
            out["seasons"].append(season)
            rest = rest[end + 1:].lstrip()
    except ValueError:
        return None
    if rest[:1].isdigit():  # a second set of hours for the same place
        return None
    if any(h["close"] <= h["open"] for h in [out] + out["seasons"]):  # overnight or odd
        return None
    return out


def _closed_token(tok, out):
    if tok in ("年中無休", "原則年中無休", "無休", "なし"):
        return True
    if tok == "年末年始":
        out["fuzzy"].append(NEW_YEAR)
        return True
    m = re.fullmatch(r"(?:毎週)?([月火水木金土日])曜日?", tok)
    if m:
        out["dow"].append(DOW[m[1]])
        return True
    m = re.fullmatch(r"第(\d(?:/\d)*)([月火水木金土日])曜日?", tok)
    if m:
        out["nth"].extend([int(n), DOW[m[2]]] for n in m[1].split("/"))
        return True
    m = (re.fullmatch(r"(\d{1,2})/(\d{1,2})日?(?:" + TILDE + r"(?:(\d{1,2})/)?(\d{1,2})日?)?", tok)
         or re.fullmatch(r"(\d{1,2})月(\d{1,2})日(?:" + TILDE + r"(?:(\d{1,2})月)?(\d{1,2})日)?", tok))
    if m:
        start = _md(m[1], m[2])
        end = _md(m[3] or m[1], m[4]) if m[4] else start
        out["dates"].append([start, end])
        return True
    return False


def parse_closed(text):
    if not text:
        return None
    t = _norm(text).strip()
    t = re.sub(r"(定休日|休館日)\s*:\s*", " ", t)
    t = re.sub(r"年末年始\s*:\s*(?=\d)", " ", t)
    t = re.sub(r"第(\d(?:,\d)+)", lambda m: "第" + m[1].replace(",", "/"), t)
    tokens = [x for x in re.split(r"[、,，\s]+", t) if x]
    if not tokens:
        return None
    out = {"dow": [], "nth": [], "dates": [], "fuzzy": []}
    try:
        if not all(_closed_token(tok, out) for tok in tokens):
            return None
    except ValueError:
        return None
    return out


def schedule(hours, closed):
    h = parse_hours(hours)
    if h is None:
        return None
    if not closed and hours:
        m = re.search(r"休館日\s*:\s*(\S+)", _norm(hours))
        closed = m[1] if m else None
    c = parse_closed(closed)
    if c is None:
        return None
    return {**h, "closed": c}
