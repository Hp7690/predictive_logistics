"""Offline assistant: answers plain-language questions (English and Hinglish) with rules and fuzzy matching only.
No network and no external model, so it keeps working at the edge. Example: "Post C ka fuel agle 7 din ka"."""
import re, difflib
from ml.india import ITEM_CATALOG
from . import alerts as al, planner as pl

ITEM_WORDS = {
    "POL": ["fuel", "pol", "petrol", "diesel", "tel", "oil", "indhan", "eendhan", "ईंधन", "पेट्रोल", "डीजल"],
    "Ration": ["ration", "rations", "rashan", "khana", "food", "राशन", "खाना"],
    "Ammo": ["ammo", "ammunition", "goli", "gola", "bullets", "गोला", "गोली"],
    "Medical": ["medical", "medicine", "medicines", "dawai", "dawa", "davai", "दवा", "दवाई"],
    "Spares": ["spare", "spares", "parts", "part", "पुर्जे"],
}
HINDI = re.compile(r"[\u0900-\u097F]|\b(ka|ki|ke|kitna|kitne|kitni|agle|din|hai|hain|kya|kahan|kab|batao|bata|dikhao|mein|me|abhi)\b", re.I)

def _lang(q):
    return "hi" if HINDI.search(q) else "en"

def _say(lang, en, hi):
    return hi if lang == "hi" else en

def _item(q):
    ql = q.lower()
    for item, words in ITEM_WORDS.items():
        for w in words:
            if (len(w) <= 3 and re.search(rf"\b{re.escape(w)}\b", ql)) or (len(w) > 3 and w in ql):
                return item
    for tok in re.findall(r"[a-z]{4,}", ql):
        for item, words in ITEM_WORDS.items():
            if difflib.get_close_matches(tok, words, n=1, cutoff=0.85):
                return item
    return None

def _posts(q, locs):
    """Find post codes mentioned: Leh, Kargil, 'post c', P3."""
    ql = q.lower(); found = []
    for l in locs:
        if l.type != "post":
            continue
        names = {l.code.lower()}
        m = re.match(r"post ([a-z]) \((.*?)\)", l.name.lower())
        if m:
            names |= {f"post {m.group(1)}"} | {w for w in re.split(r"[ ,]+", m.group(2)) if len(w) > 2 and w not in ("nubra", "spiti")}
        if any(re.search(rf"\b{re.escape(n)}\b", ql) for n in names):
            found.append(l.code)
    if not found:
        words = re.findall(r"[a-z]{4,}", ql)
        for l in locs:
            if l.type == "post":
                town = re.search(r"\((.*?)\)", l.name)
                if town and difflib.get_close_matches(town.group(1).split(",")[0].lower(), words, n=1, cutoff=0.8):
                    found.append(l.code)
    return list(dict.fromkeys(found))

def _days(q, default=7):
    m = re.search(r"(\d+)\s*(?:d\b|day|days|din|दिन)", q.lower()) or re.search(r"(?:next|agle|अगले)\s*(\d+)", q.lower())
    return max(1, min(14, int(m.group(1)))) if m else default

def answer(s, text, scope=None, role="planner"):
    from ml import forecast as fc
    q = (text or "").strip()
    if not q:
        return {"intent": "help", "answer": "Ask me about stock, forecast, shortages, routes, weather, convoys or edge nodes."}
    lang, ql = _lang(q), q.lower()
    locs = s.query(pl.m.Location).all(); lc = {l.code: l for l in locs}
    posts = _posts(q, locs); item = _item(q); n = _days(q)
    allowed = lambda p: scope is None or p in scope
    posts = [p for p in posts if allowed(p)] if posts else posts
    if _posts(q, locs) and not posts:
        return {"intent": "denied", "answer": _say(lang, "That post is outside your area. You can only ask about your own posts.", "Yeh post aapke area ke bahar hai. Aap sirf apne posts ke baare mein pooch sakte hain.")}
    rows = [r for r in al.dos_rows(s) if allowed(r["post"])]
    label = lambda i: ITEM_CATALOG[i]["label"]

    m = re.search(r"cv-\d+", ql)
    if m or (any(w in ql for w in ("convoy", "truck", "gaadi", "gadi", "cv")) and not posts):
        conv = pl.list_convoys(s)
        if m:
            c = next((x for x in conv if x["code"].lower() == m.group(0)), None)
            if not c:
                return {"intent": "convoy", "answer": _say(lang, f"No convoy {m.group(0).upper()} found.", f"{m.group(0).upper()} naam ka convoy nahi mila.")}
            where = f"{round(c['progress'] * 100)}% of the way" + ("" if c["gps_ok"] else " (last known position, GPS lost)")
            return {"intent": "convoy", "answer": _say(lang, f"{c['code']} ({c['mode']}) from {c['depot']} is {c['status'].replace('_', ' ')}, {where}. Stops: " + ", ".join(f"{x['post']} in {x['eta_h']} h" for x in c["stops"]) + ".",
                                                    f"{c['code']} ({c['mode']}) {c['depot']} se {c['status'].replace('_', ' ')} hai, raste ka {round(c['progress'] * 100)}% poora. Stops: " + ", ".join(f"{x['post']} {x['eta_h']} ghante mein" for x in c["stops"]) + ".")}
        act = [c for c in conv if c["status"] in ("approved", "loaded", "in_transit", "held")]
        return {"intent": "convoy", "answer": _say(lang, f"{len(act)} active convoy(s): " + (", ".join(f"{c['code']} ({c['status'].replace('_', ' ')})" for c in act) or "none"),
                                                 f"{len(act)} convoy active hain: " + (", ".join(f"{c['code']} ({c['status'].replace('_', ' ')})" for c in act) or "koi nahi"))}

    for pname in ("zoji", "baralacha", "kunzum"):
        if pname in ql or "pass" in ql:
            md = pl.map_data(s); ps = [x for x in md["passes"] if pname in x["name"].lower()] or md["passes"]
            txt = ", ".join(f"{x['name']} is {'open' if x['open'] else 'CLOSED'}" for x in ps)
            return {"intent": "pass", "answer": _say(lang, txt + ".", ", ".join(f"{x['name']} {'khula' if x['open'] else 'BAND'} hai" for x in ps) + ".")}

    if any(w in ql for w in ("weather", "snow", "baraf", "mausam", "visibility", "temperature")):
        w = [x for x in pl.weather_rows(s) if allowed(x["post"]) and (not posts or x["post"] in posts)]
        if not w:
            return {"intent": "weather", "answer": _say(lang, "No weather data.", "Mausam ka data nahi hai.")}
        return {"intent": "weather", "answer": " | ".join(f"{x['name']}: snow {x['snow_cm']} cm ({x['snow_3d_cm']} cm in 3 days), visibility {x['vis_km']} km, {x['temp_c']} C" for x in w[:4]), "data": w}

    if any(w in ql for w in ("edge", "node", "offline", "sensor", "rfid")):
        nodes = [x for x in pl.edge_nodes(s, scope) if not x["online"]]
        return {"intent": "edge", "answer": _say(lang, f"{len(nodes)} edge node(s) offline" + (": " + ", ".join(x["code"] for x in nodes) if nodes else ". All nodes online."),
                                               f"{len(nodes)} edge node offline hain" + (": " + ", ".join(x["code"] for x in nodes) if nodes else ". Sab node online hain."))}

    if any(w in ql for w in ("surplus", "balance", "balancing", "non-moving", "non moving", "transfer", "extra stock")) and role in ("planner", "admin"):
        b = pl.balancing(s)
        return {"intent": "balancing", "answer": _say(lang, f"{b['summary']['transfers']} suggested transfer(s) moving {b['summary']['moved_kg']} kg from surplus to shortfalls; {b['summary']['non_moving_pct']}% of stock is non-moving.",
                                                   f"{b['summary']['transfers']} transfer suggest hue ({b['summary']['moved_kg']} kg surplus se kami wali jagah); {b['summary']['non_moving_pct']}% stock non-moving hai."),
                "data": b["transfers"][:6]}

    if any(w in ql for w in ("winter", "sardi", "sardiyon")) and role in ("planner", "admin"):
        w = pl.winter_plan(s)["summary"]
        return {"intent": "winter", "answer": _say(lang, f"Winter need {w['need_t']} t, in stock {w['stock_t']} t, gap {w['gap_t']} t; the fleet can move {w['feasible_pct']}% before passes close.",
                                                f"Sardi ki zaroorat {w['need_t']} t, stock {w['stock_t']} t, kami {w['gap_t']} t; passes band hone se pehle {w['feasible_pct']}% pahunch sakta hai.")}

    if any(w in ql for w in ("forecast", "predict", "agle", "next", "demand", "kitna lagega", "need")) and posts and item:
        p = posts[0]; f, _ = fc.forecast(p, item, n); tot = round(float(f.p50.iloc[:n].sum())); hi = round(float(f.p90.iloc[:n].sum()))
        return {"intent": "forecast", "answer": _say(lang, f"{lc[p].name} will use about {tot} units of {label(item)} in the next {n} days (up to {hi} at the 90% level). Method: {f.attrs.get('method')}.",
                                                 f"{lc[p].name} ko agle {n} din mein lagbhag {tot} unit {label(item)} lagega (90% level par {hi} tak). Method: {f.attrs.get('method')}."),
                "data": f.to_dict("records")}

    if posts and item:
        r = next((x for x in rows if x["post"] == posts[0] and x["item"] == item), None)
        if r:
            return {"intent": "stock", "answer": _say(lang, f"{lc[r['post']].name} has {round(r['stock'])} units of {label(item)} ({r['fill_pct']}% of a full holding), about {r['dos']} days of supply. Status: {r['level']}.",
                                                   f"{lc[r['post']].name} ke paas {label(item)} ke {round(r['stock'])} unit hain ({r['fill_pct']}% full), lagbhag {r['dos']} din ka stock. Status: {r['level']}."), "data": r}
    if posts:
        pr = [x for x in rows if x["post"] == posts[0]]
        return {"intent": "post", "answer": _say(lang, f"{lc[posts[0]].name}: " + "; ".join(f"{label(x['item'])} {x['dos']} d ({x['level']})" for x in pr),
                                              f"{lc[posts[0]].name}: " + "; ".join(f"{label(x['item'])} {x['dos']} din ({x['level']})" for x in pr)), "data": pr}

    if any(w in ql for w in ("shortage", "critical", "kam", "khatam", "low", "alert", "danger", "risk", "sabse")):
        bad = [x for x in rows if x["level"] != "ok" and (not item or x["item"] == item)][:5]
        if not bad:
            return {"intent": "shortage", "answer": _say(lang, "No shortages predicted. All lines have 7+ days of supply.", "Koi kami nahi hai. Sab items ka 7+ din ka stock hai.")}
        return {"intent": "shortage", "answer": _say(lang, "Most urgent: " + "; ".join(f"{lc[x['post']].name} {label(x['item'])} {x['dos']} d" for x in bad),
                                                  "Sabse zaroori: " + "; ".join(f"{lc[x['post']].name} {label(x['item'])} {x['dos']} din" for x in bad)), "data": bad}
    return {"intent": "help", "answer": _say(lang, "I did not understand. Try: 'Post C fuel next 7 days', 'which posts are critical', 'is Zoji La open', 'where is CV-001', 'weather at Leh', 'winter stocking'.",
                                            "Samajh nahi aaya. Aise poochho: 'Post C ka fuel agle 7 din ka', 'kaun se post critical hain', 'Zoji La khula hai kya', 'CV-001 kahan hai'.")}
