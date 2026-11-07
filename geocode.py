"""Pins for addresses, from 国土地理院's address search (free, no key needed)."""
import json
import re
import urllib.parse

from fetch import FetchError
from regions import PREFS

SEARCH_URL = "https://msearch.gsi.go.jp/address-search/AddressSearch?q="
_STOP = re.compile(r"[\s　「『（(【]")


def clean(addr, pref):
    """The part of an address the search understands: up to the building name, with the prefecture in front."""
    a = _STOP.split(addr.strip(), maxsplit=1)[0]
    if not a.startswith(tuple(PREFS)) and 1 <= pref <= 47:
        a = PREFS[pref - 1] + a
    return a


def lookup(fetcher, addr, cache):
    """[lat, lng] for an address, or None when the search finds nothing. Answers are kept in `cache`, misses too.

    A failed download raises FetchError and is not cached, so the next run tries again.
    """
    if addr in cache:
        return cache[addr]
    text = fetcher.get(SEARCH_URL + urllib.parse.quote(addr))
    try:
        found = json.loads(text)
    except ValueError as e:
        raise FetchError(f"address search: not JSON for {addr}") from e
    pin = None
    if isinstance(found, list) and found:
        c = (found[0].get("geometry") or {}).get("coordinates") or []
        if len(c) == 2 and all(isinstance(x, (int, float)) for x in c):
            pin = [round(c[1], 6), round(c[0], 6)]
    cache[addr] = pin
    return pin
