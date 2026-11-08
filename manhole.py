"""マンホールカード: the card list on 下水道広報プラットホーム (GKP)'s site, one page per prefecture.

Only facts are kept (town, card code, round, date, where and when it's handed out).
The card pictures stay on GKP's site; the app never shows them.
"""
import re

from bs4 import BeautifulSoup

from regions import PREFS

PAGE_URL = "https://www.gk-p.jp/mhcard/?pref={:02d}"
_CODE = re.compile(r"[（(]\s*([A-Z]\d{3})\s*[)）]")
_TOWN = re.compile(r"^\S{1,10}?[市区町村郡]")
_DIGIT = re.compile(r"[0-9０-９]")


def page_url(pref):
    return PAGE_URL.format(pref)


def clean_id(name):
    """A card's id from its picture's file name, without the extension or stray characters
    (GKP's links sometimes end in a line break or a dot)."""
    name = name.strip().rstrip("/").rsplit("/", 1)[-1].strip()
    m = re.match(r"(.+?)\.(?:jpe?g|png|gif)\b", name, re.I)
    return (m.group(1) if m else name).strip(" .")


def _lines(cell):
    out = []
    for line in cell.get_text("\n").split("\n"):
        line = re.sub(r"[ \t\xa0]+", " ", line).strip()
        if line:
            out.append(line)
    return out


def _date(text):
    m = re.search(r"(\d{4})\s*[/年.-]\s*(\d{1,2})\s*[/月.-]\s*(\d{1,2})", text)
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None


def _addr(lines):
    """The first line that looks like an address: one starting with a prefecture, or a town name and a number."""
    for line in lines:
        if line.startswith(tuple(PREFS)) or (_TOWN.match(line) and _DIGIT.search(line)):
            return line
    return None


def parse_page(html, pref):
    """The cards on one prefecture page, in the manhole.json shape (without a pin)."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="table1")
    if table is None:
        return []
    cards = []
    for row in table.find_all("tr"):
        cells = row.find_all("td", recursive=False)  # the prefecture's th on its first row is skipped
        if len(cells) < 7:
            continue
        town_lines = _lines(cells[0])
        town_text = " ".join(town_lines)
        code = _CODE.search(town_text)
        town = _CODE.sub("", town_lines[0]).strip() if town_lines else ""
        img = cells[1].find("img")
        src = (img.get("src") or "") if img else ""
        stem = clean_id(src) if src.strip() else ""
        rnd = re.search(r"\d+", cells[2].get_text())
        cid = stem or f"{pref:02d}-{town}-{code.group(1) if code else ''}-{rnd.group() if rnd else ''}"
        info = _lines(cells[4])
        link = cells[6].find("a", href=True)
        cards.append({
            "id": cid,
            "pref": pref,
            "town": town,
            "code": code.group(1) if code else None,
            "round": int(rnd.group()) if rnd else None,
            "issued": _date(cells[3].get_text()),
            "place": info[0] if info else "",
            "info": "\n".join(info),
            "addr": _addr(info),
            "hours": "\n".join(_lines(cells[5])),
            "stock": link["href"] if link else " ".join(_lines(cells[6])),
        })
    return cards
