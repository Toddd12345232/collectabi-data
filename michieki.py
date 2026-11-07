"""Station lists and detail pages from michieki.jp."""
import html as htmllib
import re

from bs4 import BeautifulSoup

_MARKER = re.compile(r'<marker\s+lat="([^"]*)"\s+lng="([^"]*)"\s+html="([^"]*)"\s+eki="([^"]*)"')


def strip_prefix(name):
    return re.sub(r"^道の駅\s*", "", name.strip())


def parse_pref_xml(xml, pref):
    out = []
    for lat, lng, popup, eki in _MARKER.findall(xml):
        popup = htmllib.unescape(popup)
        m = re.search(r"/eki/(\d+)/", popup)
        if not m:
            continue
        lines = [htmllib.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.split(r"<br\s*/?>", popup)]
        addr = lines[1] if len(lines) > 1 else ""
        tel = next((re.sub(r"^電話番号\s*", "", x) for x in lines if x.startswith("電話番号")), "")
        out.append({"id": m.group(1), "name": strip_prefix(htmllib.unescape(eki)), "pref": pref,
                    "addr": addr, "tel": tel, "lat": float(lat), "lng": float(lng)})
    return out


def parse_detail(page):
    soup = BeautifulSoup(page, "html.parser")
    kana = soup.find("p", class_="kana")
    out = {"yomi": kana.get_text(strip=True) or None if kana else None, "hours": None, "closed": None}
    for td in soup.find_all("td"):
        label = td.get_text(strip=True)
        key = {"営業時間": "hours", "休館日": "closed"}.get(label)
        if key and out[key] is None:
            nxt = td.find_next_sibling("td")
            if nxt:
                out[key] = nxt.get_text(" ", strip=True) or None
    return out
