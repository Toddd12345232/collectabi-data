"""Which stations sell a regional 指定券 or 道の駅カード."""
import json
import re
import unicodedata

from apt import lines

CHUBU_URL = "https://www.chubu-michinoeki.org/"
KYUSHU = range(40, 48)
CHUBU_PREF = {"shizuoka": 22, "nagano": 20, "mie": 24, "aichi": 23}
_PREFIX = {"静岡": "shizuoka", "関東長野": "nagano", "中部長野": "nagano", "三重県": "mie", "愛知": "aichi"}
_LINE = re.compile(r"^(静岡|関東長野|中部長野|三重県|愛知)(\d{2})\s+(.+)$")


def parse_chubu(page):
    out = {k: [] for k in CHUBU_PREF}
    for line in lines(page):
        m = _LINE.match(unicodedata.normalize("NFKC", line))
        if not m:
            continue
        name = re.sub(r"\([^)]*\)", "", m[3]).strip()
        key = _PREFIX[m[1]]
        if name and name not in out[key]:
            out[key].append(name)
    return out


def load_shikoku(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)["names"]


def assign(stations, chubu, shikoku, matcher):
    """Set `shitei` and `cards` on every station. Returns names that matched no station."""
    by_id = {st["id"]: st for st in stations}
    for st in stations:
        st["shitei"] = ["kyushu"] if st["pref"] in KYUSHU else []
        st["cards"] = []
    unmatched = []
    for key, names in chubu.items():
        for name in names:
            sid = matcher.find([CHUBU_PREF[key]], name)
            if sid in by_id:
                for field in ("shitei", "cards"):
                    if key not in by_id[sid][field]:
                        by_id[sid][field].append(key)
            else:
                unmatched.append(f"{key}:{name}")
    for name in shikoku:
        sid = matcher.find([36, 37, 38, 39], name)
        if sid in by_id:
            if "shikoku" not in by_id[sid]["cards"]:
                by_id[sid]["cards"].append("shikoku")
        else:
            unmatched.append(f"shikoku:{name}")
    return unmatched
