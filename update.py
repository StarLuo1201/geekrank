#!/usr/bin/env python3
"""GeekRank daily updater: refresh prices + specs in data.json.

Env vars:
  PRICE_API   price endpoint template, "{q}" is replaced by the URL-encoded phone name
              e.g. https://your-price-service.example/price?q={q}
  PRICE_KEY   key in the JSON response holding the price (default "price")
  PRICE_AUTH  optional Authorization header value
"""
import json, os, re, sys, time, datetime, urllib.parse
import requests
from bs4 import BeautifulSoup

DATA = os.path.join(os.path.dirname(__file__), "data.json")
UA = {"User-Agent": "Mozilla/5.0 (GeekRank personal updater)"}
GSM_NEW = "https://www.gsmarena.com/new.php3"


def get(url, **kw):
    time.sleep(2)  # be polite
    r = requests.get(url, headers={**UA, **kw.pop("headers", {})}, timeout=20, **kw)
    r.raise_for_status()
    return r


def parse_specs(url):
    """Extract chipset / battery / refresh rate from a GSMArena phone page.
    GSMArena markup may change; adjust the data-spec selectors if fields come back empty."""
    soup = BeautifulSoup(get(url).text, "html.parser")
    def spec(name):
        el = soup.select_one(f'td[data-spec="{name}"]')
        return el.get_text(" ", strip=True) if el else ""
    disp = spec("displaytype")
    hz = re.search(r"(\d+)\s*Hz", disp)
    bat = re.search(r"(\d{4,5})\s*mAh", spec("batdescription1"))
    return {
        "chip": spec("chipset"),
        "battery": f"{bat.group(1)}mAh" if bat else "",
        "refresh": f"{hz.group(1)}Hz" if hz else "",
    }


def fetch_price(name):
    tpl = os.environ.get("PRICE_API")
    if not tpl:
        return None
    headers = {"Authorization": os.environ["PRICE_AUTH"]} if os.environ.get("PRICE_AUTH") else {}
    r = get(tpl.format(q=urllib.parse.quote(name)), headers=headers)
    val = r.json()
    for k in os.environ.get("PRICE_KEY", "price").split("."):
        val = val[k]
    return int(float(val))


def discover_new(known_names):
    """List the latest GSMArena releases; return ones we don't track yet."""
    soup = BeautifulSoup(get(GSM_NEW).text, "html.parser")
    out = []
    for a in soup.select("div.makers li a")[:30]:
        name = a.get_text(" ", strip=True)
        if name and name.lower() not in known_names:
            out.append({"name": name, "gsm_url": urllib.parse.urljoin(GSM_NEW, a["href"])})
    return out


def main():
    with open(DATA, encoding="utf-8") as f:
        db = json.load(f)

    for p in db["phones"]:
        # specs: only fetched when missing (they rarely change)
        if p.get("gsm_url") and not (p.get("battery") and p.get("refresh")):
            try:
                s = parse_specs(p["gsm_url"])
                p.update({k: v for k, v in s.items() if v})
            except Exception as e:
                print(f"[specs] {p['name']}: {e}", file=sys.stderr)
        # price
        try:
            new = fetch_price(p["name"])
            old = p["price"]
            if new and 0.5 * old <= new <= 1.5 * old:  # sanity guard against bad scrapes
                p["prev_price"], p["price"] = old, new
            elif new:
                print(f"[price] {p['name']}: {new} rejected (old {old})", file=sys.stderr)
        except Exception as e:
            print(f"[price] {p['name']}: {e}", file=sys.stderr)

    # new releases go to "pending": base score / category must be set by you
    try:
        known = {p["name"].lower() for p in db["phones"]} | {p["name"].lower() for p in db.get("pending", [])}
        for n in discover_new(known):
            try:
                n.update(parse_specs(n["gsm_url"]))
            except Exception as e:
                print(f"[new] {n['name']}: {e}", file=sys.stderr)
            db.setdefault("pending", []).append(n)
    except Exception as e:
        print(f"[discover] {e}", file=sys.stderr)

    db["updated_at"] = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(timespec="minutes")
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print("done", db["updated_at"])


if __name__ == "__main__":
    main()
