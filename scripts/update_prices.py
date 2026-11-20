#!/usr/bin/env python3
"""Fetch auction prices for every reagent in recipes.json and append a history point."""
import json, os, sys, time, urllib.request, datetime

HOUSE = int(os.environ.get("AH_HOUSE", "113"))          # Horde PvP, Americas
BASE = os.environ.get("AH_BASE", "https://blackwater.exchange/api/site/markets/us/1/%d" % HOUSE)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_HISTORY = 1000

def get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "enchant-tracker/1.0 (github pages)"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception as e:
            print("retry", url, e, file=sys.stderr); time.sleep(2 * (i + 1))
    return None

def load(name, default):
    try:
        with open(os.path.join(ROOT, name)) as f: return json.load(f)
    except Exception: return default

cfg = load("recipes.json", None)
old = load("prices.json", {"items": {}})
items, house_meta = {}, {}
for iid, name in cfg["items"].items():
    d = get("%s/items/%s" % (BASE, iid))
    h = next((x for x in (d or {}).get("houses", []) if x["house_id"] == HOUSE), None)
    if h is None:
        items[iid] = old["items"].get(iid, {"name": name, "min": None, "avg": None, "units": 0}); continue
    house_meta = {"id": HOUSE, "name": h["name"], "captured_at": h["captured_at"]}
    items[iid] = {"name": name,
                  "min": round(h["minimum_ask_copper"]) if h["minimum_ask_copper"] is not None else None,
                  "avg": round(h["average_ask_copper"]) if h["average_ask_copper"] is not None else None,
                  "units": h["units"]}
if not house_meta: sys.exit("no data fetched; leaving files untouched")

now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
out = {"updated": now, "house": house_meta, "items": items}

# history: avg-ask cost per recipe (None if a priced reagent has no listing)
cost = {}
for r in cfg["recipes"]:
    tot, ok = r.get("fee", 0), True
    for iid, q in r["reagents"]:
        a = items[iid]["avg"]
        if a is None: continue            # farmed / unlisted: excluded from tracked cost
        tot += a * q
    cost[r["id"]] = tot
hist = load("history.json", [])
if not hist or hist[-1]["cost"] != cost:
    hist.append({"t": now, "cost": cost})
hist = hist[-MAX_HISTORY:]

with open(os.path.join(ROOT, "prices.json"), "w") as f: json.dump(out, f, indent=1)
with open(os.path.join(ROOT, "history.json"), "w") as f: json.dump(hist, f)
print("ok", now, len(items), "items")
