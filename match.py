"""Match station names from a-pt and other sites to michieki.jp station ids."""
import re
import unicodedata


def norm(name):
    s = unicodedata.normalize("NFKC", name or "")
    s = re.sub(r"^\s*道の駅\s*", "", s)
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"[\s・/／\-ー〜~★☆]", "", s)


class Matcher:
    def __init__(self, stations, overrides):
        self.overrides = overrides
        self.by_pref = {}
        for st in stations:
            self.by_pref.setdefault(st["pref"], []).append((st["id"], norm(st["name"])))

    def find(self, prefs, name):
        raw = (name or "").strip()
        for p in prefs:
            hit = self.overrides.get(f"{p}:{raw}")
            if hit:
                return None if hit in ("none", "apt") else hit
        n = norm(raw)
        if not n:
            return None
        cands = [c for p in prefs for c in self.by_pref.get(p, [])]
        exact = [sid for sid, cn in cands if cn == n]
        if exact:
            return exact[0] if len(exact) == 1 else None
        sub = [sid for sid, cn in cands if n in cn or cn in n]
        return sub[0] if len(sub) == 1 else None
