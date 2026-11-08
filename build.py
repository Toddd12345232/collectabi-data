"""Refresh the source sections that are due, then write data.json for the app.

    python build.py --out DIR [--cache DIR] [--delay S] [--details N] [--geocode N] [--force NAME ...]

DIR/state.json keeps the raw sections between runs (only this script reads it).
DIR/data.json is what the app downloads, and DIR/manhole.json the マンホールカード list. A section that fails, or comes back
suspiciously short, keeps its previous copy; the run then exits 1 so GitHub
emails the owner.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import apt
import geocode
import manhole
import michieki
import regional
import translate
from fetch import FetchError, Fetcher
from hours import schedule
from match import Matcher, norm
from regions import APT_PAGES, MICHIEKI_XML, apt_page_url, michieki_detail_url, michieki_xml_url, pref_code

HERE = os.path.dirname(os.path.abspath(__file__))
MAX_AGE = {"michieki": timedelta(days=6), "apt_status": timedelta(hours=20), "apt_specials": timedelta(hours=20),
           "apt_notices": timedelta(hours=20), "chubu": timedelta(days=6), "manhole": timedelta(days=6)}
MIN_COUNT = {"michieki": 1150, "apt_status": 1150, "apt_specials": 100, "apt_notices": 10, "chubu": 50, "manhole": 1000}
DETAIL_FAIL_LIMIT = 0.05
DETAILS_PER_RUN = 200
DETAIL_MAX_AGE = timedelta(days=14)
DETAIL_BUDGET_SECONDS = 25 * 60  # leave time in the 60-minute job for everything else
SHORT_PAGE = 0.5  # a page with under half its previous rows is treated as broken
GEOCODE_PER_RUN = 400  # 国土地理院 address searches per run; new manhole card addresses are pinned over a few runs
GEOCODE_BUDGET_SECONDS = 8 * 60  # and never more than this, so a slow 国土地理院 can't stop the job saving
FAIL_STREAK_LIMIT = 5  # a site that fails this many times in a row is left until the next run


def _load_json(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return json.load(f)


def _short(new, old):
    return len(old) >= 5 and len(new) < len(old) * SHORT_PAGE


def _refresh_michieki(fetcher, state, now=None):
    """Station list, one XML file per prefecture (Hokkaido has six).

    A file that fails or comes back much shorter keeps its previous stations. Stations
    that drop out of a file that otherwise looks fine are kept and marked `gone`,
    so ticks for them still show.
    """
    old_by_file = {}
    for r in state.get("michieki", []):
        old_by_file.setdefault(r.get("f"), []).append(r)
    rows, problems = [], []
    for file_id, pref in MICHIEKI_XML:
        old = old_by_file.get(file_id, [])
        try:
            got = michieki.parse_pref_xml(fetcher.get(michieki_xml_url(file_id)), pref)
        except FetchError as e:
            problems.append(f"michieki: {file_id}: {e}")
            rows += old
            continue
        if _short(got, old):
            problems.append(f"michieki: {file_id} returned {len(got)} of {len(old)} stations")
            rows += old
            continue
        ids = {r["id"] for r in got}
        rows += [{**r, "f": file_id} for r in got]
        rows += [{**o, "gone": True} for o in old if o["id"] not in ids]
    return rows, len(rows), problems


def _refresh_details(fetcher, state, now, limit):
    """Read up to `limit` station pages, those never read first, then the oldest.

    michieki.jp is slow (about 3 s a page), so the 1,241 pages are spread over
    several daily runs instead of one long one.
    """
    details = dict(state.get("details", {}))
    ids = [s["id"] for s in state.get("michieki", []) if not s.get("gone")]
    due = [i for i in ids if i not in details or now - datetime.fromisoformat(details[i]["at"]) > DETAIL_MAX_AGE]
    due.sort(key=lambda i: details.get(i, {}).get("at", ""))
    started, tried, failed = time.monotonic(), 0, 0
    for sid in due[:limit]:
        if time.monotonic() - started >= DETAIL_BUDGET_SECONDS:
            break
        tried += 1
        try:
            d = michieki.parse_detail(fetcher.get(michieki_detail_url(sid), encoding="cp932"))
        except FetchError:
            failed += 1
            continue
        if not any(d.values()) and sid in details:  # an empty page: keep what we had
            d = {k: details[sid].get(k) for k in ("yomi", "hours", "closed")}
        details[sid] = {**d, "at": now.isoformat(timespec="seconds")}
    problems = []
    if tried >= 20 and failed / tried > DETAIL_FAIL_LIMIT:
        problems.append(f"details: {failed} of {tried} station pages failed")
    return details, tried, problems


def _refresh_apt_status(fetcher, state, now=None):
    """a-pt's table for each prefecture. A page that fails or comes back much shorter keeps its previous rows."""
    old_by_page = {}
    for r in state.get("apt_status", []):
        old_by_page.setdefault(r["prefs"][0], []).append(r)
    rows, problems = [], []
    for name, prefs in APT_PAGES:
        old = old_by_page.get(prefs[0], [])
        try:
            got = [{"prefs": prefs, "name": r["name"], "raw": r["raw"], "status": r["status"]}
                   for r in apt.parse_status_page(fetcher.get(apt_page_url(name)))]
        except FetchError as e:
            problems.append(f"apt_status: {name}: {e}")
            rows += old
            continue
        if _short(got, old):
            problems.append(f"apt_status: {name} returned {len(got)} of {len(old)} rows")
            rows += old
            continue
        rows += got
    return rows, len(rows), problems


def _refresh_specials(fetcher, state, now=None):
    """Special tickets. Posts that roll off the bottom of a-pt's page are kept, because ticks refer to them."""
    page = fetcher.get(apt.SPECIALS_URL)
    posts = apt.parse_specials(page)
    prev = state.get("apt_specials") or {}
    ids = {p["id"] for p in posts}
    merged = posts + [p for p in prev.get("posts", []) if p["id"] not in ids]
    merged.sort(key=lambda p: p["posted"], reverse=True)
    ended = sorted({tuple(e) for e in prev.get("ended", [])} | set(apt.parse_ended(page)))
    return {"posts": merged, "ended": [list(e) for e in ended]}, len(posts), []


def _refresh_notices(fetcher, state, now=None):
    notices = apt.parse_notices(fetcher.get(apt.NOTICES_URL))
    return notices, len(notices), []


def _refresh_chubu(fetcher, state, now=None):
    lists = regional.parse_chubu(fetcher.get(regional.CHUBU_URL))
    return lists, sum(len(v) for v in lists.values()), []


def _refresh_manhole(fetcher, state, now):
    """GKP's card list, one page per prefecture. A page that fails or comes back much shorter keeps its
    previous cards. Cards that drop off a page that otherwise looks fine are kept, with `gone` = the day."""
    prev = state.get("manhole") or {}
    old_pages = prev.get("pages", {})
    today = now.date().isoformat()
    pages, problems, streak = {}, [], 0
    for pref in range(1, 48):
        key = f"{pref:02d}"
        old = [{**o, "id": manhole.clean_id(o["id"])} for o in old_pages.get(key, [])]   # ids saved before clean_id
        if streak >= FAIL_STREAK_LIMIT:   # GKP looks down: keep the rest as they were
            pages[key] = old
            continue
        try:
            got = manhole.parse_page(fetcher.get(manhole.page_url(pref)), pref)
            streak = 0
        except FetchError as e:
            streak += 1
            problems.append(f"manhole: {key}: {e}")
            pages[key] = old
            continue
        if _short(got, [c for c in old if not c.get("gone")]):
            problems.append(f"manhole: {key} returned {len(got)} of {len(old)} cards")
            pages[key] = old
            continue
        ids = {c["id"] for c in got}
        pages[key] = got + [{**o, "gone": o.get("gone") or today} for o in old if o["id"] not in ids]
    count = len({c["id"] for cards in pages.values() for c in cards})
    return {"pages": pages, "geo": prev.get("geo", {})}, count, problems


def _manhole_addr(card):
    return geocode.clean(card["addr"], card["pref"]) if card.get("addr") else None


def _geocode_manhole(fetcher, mh, limit):
    """Look up to `limit` card addresses not searched before. Misses are remembered too."""
    geo = dict(mh.get("geo", {}))
    todo = []
    for key in sorted(mh.get("pages", {})):
        for c in mh["pages"][key]:
            a = _manhole_addr(c)
            if a and a not in geo and a not in todo:
                todo.append(a)
    tried = failed = streak = 0
    started = time.monotonic()
    for a in todo[:limit]:
        if time.monotonic() - started >= GEOCODE_BUDGET_SECONDS or streak >= FAIL_STREAK_LIMIT:
            break
        tried += 1
        try:
            geocode.lookup(fetcher, a, geo)
            streak = 0
        except FetchError:
            failed += 1
            streak += 1
    problems = []
    if streak >= FAIL_STREAK_LIMIT:
        problems.append(f"manhole: address search failed {streak} times in a row; trying again next run")
    elif tried >= 20 and failed / tried > DETAIL_FAIL_LIMIT:
        problems.append(f"manhole: {failed} of {tried} address searches failed")
    return {**mh, "geo": geo}, problems


def derive_manhole(state, now):
    """manhole.json: every card once (the first prefecture page that lists it), with its pin when found."""
    mh = state.get("manhole") or {}
    if not mh.get("pages"):
        return None
    geo = mh.get("geo", {})
    cards, seen = [], set()
    for key in sorted(mh["pages"]):
        for c in mh["pages"][key]:
            c = {**c, "id": manhole.clean_id(c["id"])}
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            pin = geo.get(_manhole_addr(c) or "")
            cards.append({**c, "lat": pin[0] if pin else None, "lng": pin[1] if pin else None})
    return {"v": 1, "built": now.isoformat(timespec="seconds"), "cards": cards}


REFRESH = {
    "michieki": _refresh_michieki,
    "apt_status": _refresh_apt_status,
    "apt_specials": _refresh_specials,
    "apt_notices": _refresh_notices,
    "chubu": _refresh_chubu,
    "manhole": _refresh_manhole,
}


def build(fetcher, prev, now, force=frozenset(), details_per_run=None, translator=None, geocode_per_run=None):
    """Returns (state, data.json or None, errors, manhole.json or None)."""
    state = dict(prev or {})
    sources = dict(state.get("sources", {}))
    errors = []
    for name, refresh in REFRESH.items():
        last = sources.get(name)
        if name not in force and last and now - datetime.fromisoformat(last) < MAX_AGE[name]:
            continue
        try:
            value, count, problems = refresh(fetcher, state, now)
            if count < MIN_COUNT[name]:
                raise ValueError(f"only {count} items")
        except Exception as e:  # keep the previous copy of this section
            errors.append(f"{name}: {e}")
            continue
        errors.extend(problems)
        state[name] = value
        sources[name] = now.isoformat(timespec="seconds")
    if state.get("michieki"):
        try:
            limit = DETAILS_PER_RUN if details_per_run is None else details_per_run
            state["details"], tried, problems = _refresh_details(fetcher, state, now, limit)
            errors.extend(problems)
            if tried:
                sources["details"] = now.isoformat(timespec="seconds")
        except Exception as e:
            errors.append(f"details: {e}")
    if state.get("manhole"):
        try:
            limit = GEOCODE_PER_RUN if geocode_per_run is None else geocode_per_run
            state["manhole"], problems = _geocode_manhole(fetcher, state["manhole"], limit)
            errors.extend(problems)
        except Exception as e:
            errors.append(f"manhole: address search: {e}")
    state["sources"] = sources
    # Translation problems are notes, not errors: the Japanese still shows, so they never fail the run.
    state["notes"] = []
    if translator is not None and state.get("apt_specials"):
        cache, used, notes = translate.translate_specials(state["apt_specials"]["posts"], state.get("translations", {}),
                                                          now.date(), translator, getattr(translator, "budget", translate.MYMEMORY_DAILY))
        state["translations"] = cache
        state["notes"] = notes + [f"translation: {used} characters with {translator.name}"]
    cards = derive_manhole(state, now)
    if not state.get("michieki"):
        return state, None, errors, cards
    data = derive(state, now)
    state["aptonly"] = [s["id"] for s in data["stations"] if s["id"].startswith("apt-")]
    return state, data, errors, cards


def derive(state, now):
    overrides = _load_json("overrides.json")
    details = state.get("details", {})
    stations = []
    for b in state["michieki"]:
        d = details.get(b["id"], {})
        st = {**{k: v for k, v in b.items() if k != "f"}, "yomi": d.get("yomi"), "hours": d.get("hours"), "closed": d.get("closed")}
        st.update({"sched": schedule(st["hours"], st["closed"]), "apt": None, "shitei": [], "cards": [], "alias": []})
        stations.append(st)
    by_id = {s["id"]: s for s in stations}
    matcher = Matcher(state["michieki"], overrides)
    aliases = dict(state.get("aliases", {}))
    was_aptonly = set(state.get("aptonly", []))
    for row in state.get("apt_status", []):
        if any(overrides.get(f"{p}:{row['name'].strip()}") == "none" for p in row["prefs"]):
            continue
        info = {"status": row["status"], "raw": row["raw"], "name": row["name"]}
        aptid = f"apt-{row['prefs'][0]}-{norm(row['name'])}"
        sid = matcher.find(row["prefs"], row["name"])
        if sid in by_id:
            if by_id[sid]["apt"] is None:
                by_id[sid]["apt"] = info
            if aptid in was_aptonly:
                aliases[aptid] = sid
        elif aptid not in by_id:
            st = {"id": aptid, "name": row["name"], "yomi": None, "pref": row["prefs"][0], "addr": "", "tel": "",
                  "lat": None, "lng": None, "hours": None, "closed": None, "sched": None, "apt": info,
                  "shitei": [], "cards": [], "alias": []}
            stations.append(st)
            by_id[aptid] = st
    for aptid, sid in aliases.items():
        if sid in by_id and aptid not in by_id[sid]["alias"]:
            by_id[sid]["alias"].append(aptid)
    state["aliases"] = aliases
    shikoku = _load_json("shikoku_cards.json")["names"]
    regional.assign(stations, state.get("chubu", {}), shikoku, Matcher(stations, overrides))

    specials = []
    translations = state.get("translations", {})
    for p in (state.get("apt_specials") or {}).get("posts", []):
        code = pref_code(p["pref"])
        sid = matcher.find([code], p["station"]) if code else None
        sp = {**p, "st": sid if sid in by_id else None}
        tr = translations.get(p["id"])
        if tr:
            sp["tr"] = {k: v for k, v in tr.items() if k != "key"}
        specials.append(sp)
    for name, day in (state.get("apt_specials") or {}).get("ended", []):
        same = [s for s in specials if norm(s["station"] or "") == norm(name) and s["posted"] <= day]
        if same:
            max(same, key=lambda s: s["posted"])["ended"] = day
    notices = []
    for n in state.get("apt_notices", []):
        code = pref_code(n["pref"])
        st = matcher.find([code], n["station"]) if code and n["station"] else None
        notices.append({**n, "st": st if st in by_id else None})
    return {"v": 1, "built": now.isoformat(timespec="seconds"), "sources": state["sources"],
            "stations": stations, "specials": specials, "notices": notices}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write(path, obj, compact):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def main(argv, fetcher=None):
    ap = argparse.ArgumentParser(prog="python build.py")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache")
    ap.add_argument("--delay", type=float, default=1.0)
    ap.add_argument("--force", nargs="*", default=[], choices=list(MAX_AGE))
    ap.add_argument("--details", type=int, default=DETAILS_PER_RUN, help="station pages to read this run")
    ap.add_argument("--geocode", type=int, default=GEOCODE_PER_RUN, help="manhole card addresses to look up this run")
    ap.add_argument("--no-translate", action="store_true", help="skip translating special tickets")
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    fetcher = fetcher or Fetcher(cache_dir=args.cache, delay=args.delay)
    prev = _read(os.path.join(args.out, "state.json"))
    translator = None if args.no_translate else translate.backend_from_env()
    state, data, errors, cards = build(fetcher, prev, datetime.now(timezone.utc), set(args.force), args.details, translator,
                                       args.geocode)
    for n in state.get("notes", []):
        print("NOTE", n, file=sys.stderr)
    for e in errors:
        print("ERROR", e, file=sys.stderr)
    if data is None:
        print("No station list, nothing written.", file=sys.stderr)
        return 1
    _write(os.path.join(args.out, "state.json"), state, compact=False)
    _write(os.path.join(args.out, "data.json"), data, compact=True)
    if cards:
        _write(os.path.join(args.out, "manhole.json"), cards, compact=True)
    pinned = sum(1 for c in (cards or {}).get("cards", []) if c["lat"] is not None)
    print(f"{len(data['stations'])} stations, {len(data['specials'])} specials, {len(data['notices'])} notices, "
          f"{len((cards or {}).get('cards', []))} manhole cards ({pinned} with a pin)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
