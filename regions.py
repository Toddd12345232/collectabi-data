"""Prefectures, 道の駅 blocks, and the source pages for each."""
from urllib.parse import quote

PREFS = ["北海道", "青森県", "岩手県", "宮城県", "秋田県", "山形県", "福島県", "茨城県", "栃木県", "群馬県",
         "埼玉県", "千葉県", "東京都", "神奈川県", "新潟県", "富山県", "石川県", "福井県", "山梨県", "長野県",
         "岐阜県", "静岡県", "愛知県", "三重県", "滋賀県", "京都府", "大阪府", "兵庫県", "奈良県", "和歌山県",
         "鳥取県", "島根県", "岡山県", "広島県", "山口県", "徳島県", "香川県", "愛媛県", "高知県", "福岡県",
         "佐賀県", "長崎県", "熊本県", "大分県", "宮崎県", "鹿児島県", "沖縄県"]


def _blocks():
    out = {1: "hokkaido"}
    for c in range(2, 8):
        out[c] = "tohoku"
    for c in list(range(8, 15)) + [19, 20]:
        out[c] = "kanto"
    for c in (15, 16, 17):
        out[c] = "hokuriku"
    for c in range(21, 25):
        out[c] = "chubu"
    for c in [18] + list(range(25, 31)):
        out[c] = "kinki"
    for c in range(31, 36):
        out[c] = "chugoku"
    for c in range(36, 40):
        out[c] = "shikoku"
    for c in range(40, 48):
        out[c] = "kyushu"
    return out


BLOCK_OF = _blocks()

MICHIEKI_XML = [(f"01{x}", 1) for x in "abcdef"] + [(f"{c:02d}", c) for c in range(2, 48)]


def michieki_xml_url(file_id):
    return f"https://www.michieki.jp/xml/pref/pref{file_id}.xml"


def michieki_detail_url(station_id):
    return f"https://www.michieki.jp/eki/{station_id}/"


APT_PAGES = [("東京都-神奈川県", [13, 14])] + [(p, [i + 1]) for i, p in enumerate(PREFS) if i + 1 not in (13, 14)]


def apt_page_url(name):
    return "https://www.a-pt.co.jp/" + quote(f"ご注文-注文用紙/{name}") + "/"


def pref_code(name):
    """Prefecture code from a name such as 鹿児島県 or 鹿児島, or None."""
    name = (name or "").strip()
    for i, p in enumerate(PREFS):
        if name == p or (len(name) >= 2 and p.startswith(name)):
            return i + 1
    return None
