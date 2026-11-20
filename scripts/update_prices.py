#!/usr/bin/env python3
"""Fetch Horde PvP (US) auction prices straight from Blizzard's Game Data API for every reagent in
recipes.json, and append a history point.  Needs BNET_CLIENT_ID / BNET_CLIENT_SECRET (free, from
https://develop.battle.net/access/clients)."""
import base64, json, os, sys, time, urllib.parse, urllib.request, urllib.error, datetime, email.utils

REGION = os.environ.get("AH_REGION", "us")
HOUSE = int(os.environ.get("AH_HOUSE", "113"))          # Horde PvP (Alliance 110, Blackwater 116)
RULESET = os.environ.get("AH_RULESET", "1")             # ignored by the API, the house id decides
API = os.environ.get("AH_API", "https://%s.api.blizzard.com" % REGION)
TOKEN_URL = os.environ.get("AH_TOKEN_URL", "https://oauth.battle.net/token")
NS = "dynamic-forever-%s" % REGION
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_HISTORY = 1000

def http(url, headers=None, data=None, tries=3, timeout=120):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers or {}, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r), r.headers
        except urllib.error.HTTPError as e:
            print("HTTP %s from %s: %s" % (e.code, url.split("?")[0], e.read()[:200].decode("utf-8", "replace")), file=sys.stderr)
            if e.code in (400, 401, 403, 404): return None, None
        except Exception as e:
            print("ERROR %s from %s: %r" % (type(e).__name__, url.split("?")[0], e), file=sys.stderr)
        time.sleep(3 * (i + 1))
    return None, None

def load(name, default):
    try:
        with open(os.path.join(ROOT, name)) as f: return json.load(f)
    except Exception: return default

def token():
    cid, sec = os.environ.get("BNET_CLIENT_ID"), os.environ.get("BNET_CLIENT_SECRET")
    if not cid or not sec:
        sys.exit("FAILED: BNET_CLIENT_ID / BNET_CLIENT_SECRET are not set (add them as repository secrets)")
    auth = base64.b64encode(("%s:%s" % (cid, sec)).encode()).decode()
    d, _ = http(TOKEN_URL, {"Authorization": "Basic " + auth, "Content-Type": "application/x-www-form-urlencoded"},
                b"grant_type=client_credentials")
    if not d or "access_token" not in d: sys.exit("FAILED: could not get a Battle.net access token (check the client id/secret)")
    return d["access_token"]

def fetch_units(tok, wanted):
    """Return ({item_id: [(unit_price_copper, qty), ...]}, last_modified_iso)."""
    units, stamp = {}, None
    for suffix, is_commodity in (("/commodities", True), ("", False)):
        url = "%s/data/wow/ruleset/%s/auctions/%d%s?%s" % (API, RULESET, HOUSE, suffix,
              urllib.parse.urlencode({"namespace": NS, "locale": "en_US"}))
        d, hdr = http(url, {"Authorization": "Bearer " + tok})
        if d is None:
            if is_commodity: sys.exit("FAILED: could not download auctions for house %d (see errors above)" % HOUSE)
            continue
        if hdr and hdr.get("Last-Modified") and not stamp:
            try: stamp = email.utils.parsedate_to_datetime(hdr["Last-Modified"]).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception: pass
        for a in d.get("auctions", []):
            iid = str(a["item"]["id"])
            if iid not in wanted: continue
            q = a.get("quantity", 1) or 1
            p = a.get("unit_price") if is_commodity else (a.get("buyout") or 0) / q
            if p: units.setdefault(iid, []).append((p, q))
    return units, stamp

def summarize(lst):
    if not lst: return {"min": None, "avg": None, "units": 0}
    lst.sort()
    total = sum(q for _, q in lst)
    cap = max(1, round(total * 0.15)); got = 0; acc = 0.0
    for p, q in lst:                       # market price: mean of the cheapest ~15% of units
        take = min(q, cap - got)
        if take <= 0: break
        acc += p * take; got += take
    return {"min": round(lst[0][0]), "avg": round(acc / got), "units": total}

cfg = load("recipes.json", None)
old = load("prices.json", {"items": {}})
units, stamp = fetch_units(token(), set(cfg["items"]))
items = {iid: dict(name=name, **summarize(units.get(iid, []))) for iid, name in cfg["items"].items()}

now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
out = {"updated": now, "house": {"id": HOUSE, "name": "Horde Auction House · PvP", "captured_at": stamp or now, "source": "Blizzard Game Data API"},
       "items": items}

cost = {}
for r in cfg["recipes"]:
    tot = r.get("fee", 0)
    for iid, q in r["reagents"]:
        a = items[iid]["avg"]
        if a is not None: tot += a * q
    cost[r["id"]] = tot
hist = load("history.json", [])
if not hist or hist[-1]["cost"] != cost: hist.append({"t": now, "cost": cost})
hist = hist[-MAX_HISTORY:]

with open(os.path.join(ROOT, "prices.json"), "w") as f: json.dump(out, f, indent=1)
with open(os.path.join(ROOT, "history.json"), "w") as f: json.dump(hist, f)
print("ok", now, len(items), "items;", sum(1 for v in items.values() if v["units"]), "have listings")
