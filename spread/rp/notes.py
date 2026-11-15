"""Dealer-note parser. Python port of source-exp/RoutePulse typescript/notes.ts (Junction 2026, Spread).
JavaScript regexes are ASCII for \\b, \\w and \\d, so every pattern here uses re.ASCII."""
from __future__ import annotations

import math
import re
from typing import Optional

DAY_MINUTES = 1440
A = re.ASCII
AI = re.ASCII | re.IGNORECASE


def new_note(leg) -> dict:
    return {
        "readyAt": leg["pickup"]["window"]["from"],
        "releasedAt": None,
        "pickupHours": copy_hours(leg["pickup"].get("hours")),
        "deliveryHours": copy_hours(leg["delivery"].get("hours")),
        "manualGearbox": False,
        "needsPlates": False,
        "summerTyres": False,
        "noteDeadline": None,
    }


def copy_hours(h):
    if not h:
        return None
    return {"opens": h["opens"], "closes": h["closes"], "weekdays": list(h["weekdays"]),
            "saturday": dict(h["saturday"]) if h.get("saturday") else None}


def fold_ascii(s: str) -> str:
    s = s.lower()
    s = re.sub("[äå]", "a", s)
    s = s.replace("ö", "o")
    return re.sub("[–—−]", "-", s)


def damerau_levenshtein1(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    i = 0
    while i < la and i < lb and a[i] == b[i]:
        i += 1
    if i == la and i == lb:
        return True
    if la == lb:
        if a[i + 1:] == b[i + 1:]:
            return True
        return i + 1 < la and a[i] == b[i + 1] and a[i + 1] == b[i] and a[i + 2:] == b[i + 2:]
    return a[i:] == b[i + 1:] if la < lb else a[i + 1:] == b[i:]


_DEDUP3 = re.compile(r"([a-z])\1{2,}", A)


def dedup3(s: str) -> str:
    return _DEDUP3.sub(r"\1\1", s)


def approx_token(tok: str, target: str) -> bool:
    if tok == target:
        return True
    if len(target) < 5:
        return False
    t1 = dedup3(tok)
    return t1 == target or damerau_levenshtein1(t1, target)


def approx_prefix(tok: str, prefix: str) -> bool:
    if tok.startswith(prefix):
        return True
    if len(prefix) < 5 or len(tok) < len(prefix) - 1:
        return False
    t1 = dedup3(tok)
    if t1.startswith(prefix):
        return True
    for ln in (len(prefix) - 1, len(prefix), len(prefix) + 1):
        if 0 < ln <= len(t1) and damerau_levenshtein1(t1[:ln], prefix):
            return True
    return False


_TOK = re.compile(r"[a-z0-9]+", A)


def tokenize_folded(s: str) -> list[str]:
    return _TOK.findall(fold_ascii(s))


def has_any_stem(text: str, exact_short, stems_long) -> bool:
    for tok in tokenize_folded(text):
        if tok in exact_short:
            return True
        for st in stems_long:
            if approx_prefix(tok, st):
                return True
    return False


_KEEP_AFTER_NEG = re.compile(r"\s*(?:kun\b|ennen\b|before\b|fore\b|förrän\b|forran\b|ready\b|valmi\w*|klar\b)", AI)
_NEG_PAREN = re.compile(r"\(\s*(?:not|no|ei|inte)\b([^)]*)\)", AI)
_NEG_CONTRAST = re.compile(r"(?:^|[,\s])\b(?:not|ei|inte)\b([^,.;!?]*?)\b(?:vaan|utan|but)\b", AI)
_NEG_COMMA = re.compile(r",\s*(?:not|ei|inte)\b([^,.;!?]*)", AI)
_BUT = re.compile(r"\b(?:vaan|utan|men|but)\b", AI)


def strip_negations(clause: str) -> str:
    def keep_or_blank(m):
        return m.group(0) if _KEEP_AFTER_NEG.search(m.group(1)) else " "

    s = _NEG_PAREN.sub(keep_or_blank, clause)
    s = _NEG_CONTRAST.sub(keep_or_blank, s)

    def comma(m):
        rest = m.group(1)
        if _KEEP_AFTER_NEG.search(rest) or _BUT.search(rest):
            return m.group(0)
        return " "

    return _NEG_COMMA.sub(comma, s)


_NOISE1 = re.compile(r"\b(?:soita|ilmoita|call|ring|notify)\b[^.!?;,/]*", AI)
_NOISE2 = re.compile(r"\b(?:viite(?:nro|numero)?|tilaus(?:nro|numero)?|varaus(?:nro|numero)?|booking\s*ref|our\s*ref|order\s*no|order\s*nr|ordern+r|referens|ref|koodi|kod|code|ruudussa|bay|plats)\b[:\s]*\d+", AI)
_NOISE3 = re.compile(r"\b\d+\s*(?:[a-zäöå]*ren[a-zäöå]*|sarjaa|sets?|wheels?|tyres?|tires?|d[aä]ck[a-zäöå]*|tkm|km|min)\b", AI)


def strip_numeric_noise(s: str) -> str:
    s = _NOISE1.sub(" ", s)
    s = _NOISE2.sub(" ", s)
    return _NOISE3.sub(" ", s)


WORD_HOUR_STEMS = [
    (11, ["yksitoist", "yhdeltatoist", "yhdestatoist", "yhdentoist", "yhteentoist", "elva", "eleven"], []),
    (12, ["kaksitoist", "kahdeltatoist", "kahdestatoist", "kahdentoist", "kahteentoist", "tolv", "twelve"], ["noon", "midday"]),
    (9, ["yhdeks", "nine"], ["nio"]),
    (10, ["kymmen"], ["tio", "ten"]),
    (13, ["yhdelt", "yhdest", "yhteen"], ["yksi", "yhden", "ett", "one"]),
    (14, ["kahdelt", "kahdest", "kahteen", "kahta", "kaksi", "kahden"], ["tva", "two"]),
    (15, ["kolmel", "kolmes", "kolmeen", "kolme", "kolmen", "three"], ["tre"]),
    (16, ["neljal", "neljas", "neljaan", "nelja", "neljan"], ["fyra", "four"]),
    (17, ["viidel", "viides", "viiteen", "viisi", "viiden"], ["fem", "five"]),
    (18, ["kuudel", "kuudes", "kuuteen", "kuusi", "kuuden"], ["sex", "six"]),
    (7, ["seitsem", "seven"], ["sju"]),
    (8, ["kahdeks", "eight"], ["atta"]),
]


def match_word_hour_token(tok: str) -> Optional[int]:
    for hour, stems, exact in WORD_HOUR_STEMS:
        if tok in exact:
            return hour
        for st in stems:
            if approx_prefix(tok, st):
                return hour
    return None


def parse_minutes_hm(h: int, m: int, ampm: Optional[str] = None) -> Optional[int]:
    if h < 0 or h > 24 or m < 0 or m > 59:
        return None
    hour = h
    if ampm:
        ap = ampm.lower()
        if ap == "pm" and hour < 12:
            hour += 12
        if ap == "am" and hour == 12:
            hour = 0
    if hour == 24 and m > 0:
        return None
    return hour * 60 + m


def _num(g) -> int:
    return int(g) if g is not None else 0


_RANGE_FI = re.compile(r"\b(\d{1,2})(?:[.:](\d{2}))?\s*:(?:sta|lta)\s*(\d{1,2})(?:[.:](\d{2}))?\s*:(?:een|aan)\b", A)
_RANGE_NUM = re.compile(r"\b(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)?\s*-\s*(\d{1,2})(?:[.:](\d{2}))?\s*(am|pm)?\b", A)


def extract_range(clause: str):
    f = fold_ascii(clause)
    m = _RANGE_FI.search(f)
    if m:
        o = parse_minutes_hm(int(m[1]), _num(m[2]))
        c = parse_minutes_hm(int(m[3]), _num(m[4]))
        if o is not None and c is not None and o < c:
            return {"opens": o, "closes": c}
    m = _RANGE_NUM.search(f)
    if m:
        o = parse_minutes_hm(int(m[1]), _num(m[2]), m[3])
        c = parse_minutes_hm(int(m[4]), _num(m[5]), m[6])
        if o is not None and c is not None and o < c:
            return {"opens": o, "closes": c}
    return None


_DAY_RANGE1 = re.compile(r"\b(?:ma|man|mon)\s*-\s*(?:pe|fre|fri)\b", A)
_DAY_RANGE2 = re.compile(r"\b(?:maanantai\w*|mandag\w*|monday)\s*-\s*(?:perjantai\w*|fredag\w*|friday)\b", A)
_DAT = re.compile(r"\bday\s+after\s+tomorrow\b", A)
_IMORG = re.compile(r"\bi\s+morg[a-z]*\b", A)
_IDAG = re.compile(r"\bi\s+dag\b", A)
_DIGIT0 = re.compile(r"^\d", A)

WEEKDAY_DEFS = [
    (0, ["ma", "man", "mon"], ["maanant", "mandag", "monday"]),
    (1, ["ti", "tis", "tue", "tues"], ["tiist", "tisdag", "tuesday"]),
    (2, ["ke", "ons", "wed"], ["keskiv", "onsdag", "wednesday"]),
    (3, ["to", "tor", "tors", "thu", "thur", "thurs"], ["torst", "torsdag", "thursday"]),
    (4, ["pe", "fre", "fri"], ["perjant", "fredag", "friday"]),
    (5, ["la", "lor", "sat"], ["lauant", "lordag", "saturday"]),
    (6, ["su", "son", "sun"], ["sunnunt", "sondag", "sunday"]),
]
ENGLISH_TO_NEXT = ["destination", "arrive", "collect", "pick", "pickup", "deliver", "the", "us", "you", "take", "bring"]


def extract_day(fragment: str, arrived_at: int) -> Optional[int]:
    arr_day = arrived_at // DAY_MINUTES
    f = _DAY_RANGE2.sub(" ", _DAY_RANGE1.sub(" ", fold_ascii(fragment)))
    if _DAT.search(f):
        return arr_day + 2
    toks = _TOK.findall(f)
    for t in toks:
        if approx_token(t, "ylihuomenna") or approx_token(t, "overmorgon"):
            return arr_day + 2
    if _IMORG.search(f):
        return arr_day + 1
    for t in toks:
        if t in ("tmrw", "tmw") or approx_token(t, "huomenna") or approx_token(t, "imorgon") or approx_token(t, "tomorrow"):
            return arr_day + 1
    if _IDAG.search(f):
        return arr_day
    for t in toks:
        if t == "idag" or approx_token(t, "tanaan") or approx_token(t, "today"):
            return arr_day
    for idx, t in enumerate(toks):
        for wd, exact, stems in WEEKDAY_DEFS:
            matched = False
            if t in exact:
                prev = toks[idx - 1] if idx >= 1 else ""
                nxt = toks[idx + 1] if idx + 1 < len(toks) else ""
                if t == "to":
                    matched = nxt not in ENGLISH_TO_NEXT and prev not in ("up", "from", "prior", "due")
                elif t == "man":
                    matched = bool(_DIGIT0.search(nxt)) or nxt in ("kl", "klockan", "klo") or prev in ("senast", "tidigast", "pa")
                else:
                    matched = True
            else:
                matched = any(approx_prefix(t, st) for st in stems)
            if matched:
                for d in range(2, 9):
                    if (arr_day + d) % 7 == wd:
                        return arr_day + d
    return None


_HALF_DIGIT = re.compile(r"^\d{1,2}$", A)
_M4 = re.compile(r"\b(?:klo|kl|kello|klockan|kockan)\s*(\d{2})(\d{2})\b", A)
_MHM = re.compile(r"\b(\d{1,2})[.:](\d{2})\s*(am|pm)?\b", A)
_MAP = re.compile(r"\b(\d{1,2})\s*(am|pm)\b", A)
_MKLO = re.compile(r"\b(?:klo|kl\.?|kello|klockan|kockan)\s*(\d{1,2})\b", A)
_MINF = re.compile(r"\b(\d{1,2})\s*:(?:sta|lta|een|aan)\b", A)
_MBARE = re.compile(r"\b(\d{1,2})\b", A)


def _half_digit_hour(s: str) -> Optional[int]:
    if not _HALF_DIGIT.search(s):
        return None
    n = int(s)
    if 1 <= n <= 5:
        return n + 12
    if 6 <= n <= 23:
        return n
    return None


def extract_clock_minutes(fragment: str) -> Optional[int]:
    f = fold_ascii(fragment)
    toks = _TOK.findall(f)
    for i in range(len(toks) - 1):
        t = toks[i]
        if t == "half" and toks[i + 1] == "past" and i + 2 < len(toks):
            nxt = toks[i + 2]
            wh = match_word_hour_token(nxt)
            if wh is None:
                wh = _half_digit_hour(nxt)
            if wh is not None:
                return wh * 60 + 30
        if t in ("halv", "half") or approx_token(t, "puoli"):
            nxt = toks[i + 1]
            wh = match_word_hour_token(nxt)
            if wh is None:
                wh = _half_digit_hour(nxt)
            if wh is not None:
                return wh * 60 - 30
    m = _M4.search(f)
    if m:
        r = parse_minutes_hm(int(m[1]), int(m[2]))
        if r is not None:
            return r
    m = _MHM.search(f)
    if m:
        r = parse_minutes_hm(int(m[1]), int(m[2]), m[3])
        if r is not None:
            return r
    m = _MAP.search(f)
    if m:
        r = parse_minutes_hm(int(m[1]), 0, m[2])
        if r is not None:
            return r
    m = _MKLO.search(f)
    if m:
        r = parse_minutes_hm(int(m[1]), 0)
        if r is not None:
            return r
    m = _MINF.search(f)
    if m:
        r = parse_minutes_hm(int(m[1]), 0)
        if r is not None:
            return r
    m = _MBARE.search(f)
    if m:
        h = int(m[1])
        if 6 <= h <= 23:
            return h * 60
    for t in toks:
        wh = match_word_hour_token(t)
        if wh is not None:
            return wh * 60
    return None


_SLASH = re.compile(r"\s+/\s+", A)
_DOTDIGIT = re.compile(r"(\d)\.(\d)", A)
_ABBR = re.compile(r"\b(kl|klo|viim|ma|ti|ke|to|pe|la|su|mån|tis|ons|tor|tors|fre|lör|sön|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|n|t|oik|mvh|br)\.", AI)
_SPLIT = re.compile(r"[.!?;]+", A)
_CORR_START = re.compile(r"^(?:korjaus|correction|rattelse)\b", A)
_CORR_PREFIX = re.compile(r"^[^:]*:\s*", A)


def split_clauses(raw: str) -> list[str]:
    pre = _SLASH.sub(". ", raw)
    prot = _ABBR.sub(r"\1", _DOTDIGIT.sub(r"\1:\2", pre))
    parts = [s.strip() for s in _SPLIT.split(prot)]
    parts = [s for s in parts if s]
    merged: list[str] = []
    for p in parts:
        fp = fold_ascii(p)
        if merged and _CORR_START.search(fp):
            merged[-1] += " __CORR__ " + _CORR_PREFIX.sub("", p, count=1)
        else:
            merged.append(p)
    return merged


_CORR = re.compile(r"(?:\b__CORR__\b|,\s*(?:ei\s*kun|eikun|tai\s+siis|sorry(?:\s*,?\s*i\s+mean)?|i\s+mean|actually|nej\s+forlat|nej\s+förlåt|eller\s+rattare\s+sagt|rattare\s+sagt)\b|\b(?:ei\s*kun|eikun)\b)", AI)


def split_correction(clause: str):
    clean = strip_numeric_noise(strip_negations(clause))
    parts = _CORR.split(clean)
    if len(parts) >= 2:
        return parts[0], parts[-1], clean
    return clean, None, clean


def extract_day_and_clock(clause: str, arrived_at: int) -> Optional[int]:
    base, corr, _ = split_correction(clause)
    arr_day = arrived_at // DAY_MINUTES
    base_day = extract_day(base, arrived_at)
    base_min = extract_clock_minutes(base)
    corr_day = extract_day(corr, arrived_at) if corr else None
    corr_min = extract_clock_minutes(corr) if corr else None
    final_min = corr_min if corr_min is not None else base_min
    if final_min is None:
        return None
    final_day = corr_day if corr_day is not None else base_day if base_day is not None else arr_day
    return final_day * DAY_MINUTES + final_min


def extract_corrected_minutes(clause: str) -> Optional[int]:
    base, corr, _ = split_correction(clause)
    base_min = extract_clock_minutes(base)
    corr_min = extract_clock_minutes(corr) if corr else None
    return corr_min if corr_min is not None else base_min


def shift_deadline_business_days(deadline: int, shift: int) -> int:
    if shift <= 0:
        return deadline
    day = math.floor(deadline / DAY_MINUTES)
    tod = deadline % DAY_MINUTES
    rem = shift
    while rem > 0:
        day += 1
        wd = day % 7
        if wd != 5 and wd != 6:
            rem -= 1
    return min(7 * DAY_MINUTES + tod, day * DAY_MINUTES + tod)


_NOT_MAN = re.compile(r"\b(?:ei|not|no|inte)\s+man[a-z]+\b", A)
_STICK = re.compile(r"\bstick\s+shift\b", A)
_I_BILEN = re.compile(r"\bi\s+bilen\b", A)
_MUST_THERE = re.compile(r"\bmust\s+be\s+there\b", A)
_MASTE = re.compile(r"\bmaste\s+vara\s+dar\b", A)
_SKA = re.compile(r"\bska\s+vara\s+pa\s+plats\s+senast\b", A)
_NO_LATER = re.compile(r"\bno\s+later\s+than\b", A)
_MUST_ARRIVE = re.compile(r"\bmust\s+arrive\b", A)
_NOT_BEFORE = re.compile(r"\b(?:ei\s+ennen|not\s+before|not\s+ready\s+before|inte\s+fore|inte\s+klar\s+forran|wont\s+be\s+ready\s+until)\b", A)
_WE_CLOSE = re.compile(r"\bwe\s+close\b", A)
_SHOP_CLOSE = re.compile(r"\bshop\s+close", A)
_INGEN = re.compile(r"\bingen\s+utlamning\b", A)
_EI_ENAA = re.compile(r"\bei\s+enaa\s+luovutuks", A)
_VOI_NOUTAA = re.compile(r"\b(?:voi\s+noutaa|saa\s+hakea|pickup\s+from|kan\s+hamta)\b", A)


def parse_dealer_note(request) -> list[dict]:
    note = request.get("note")
    max_option_deadline = max(o["deadline"] for o in request["options"])
    legs = [new_note(leg) for leg in request["legs"]]
    if not note or not note["text"].strip() or not legs:
        return legs
    leg0 = legs[0]
    req_leg0 = request["legs"][0]
    last_idx = len(legs) - 1
    last_leg = legs[last_idx]
    req_last_leg = request["legs"][last_idx]

    clauses = split_clauses(note["text"])
    stripped = [strip_numeric_noise(strip_negations(c)) for c in clauses]
    full_no_neg = " . ".join(stripped)

    manual_text = _NOT_MAN.sub(" ", fold_ascii(full_no_neg))
    if _STICK.search(manual_text) or has_any_stem(manual_text, [], ["manuaal", "manual", "manuell", "kasivaiht"]):
        leg0["manualGearbox"] = True

    for tok in tokenize_folded(full_no_neg):
        if tok in ("latest", "later", "plats"):
            continue
        if (approx_token(tok, "plates") or approx_token(tok, "kilvet") or approx_token(tok, "kilpia") or approx_token(tok, "skyltar")
                or approx_token(tok, "unregistered") or approx_prefix(tok, "siirtokilv") or approx_prefix(tok, "koekilv")
                or approx_prefix(tok, "rekisterikilv") or approx_prefix(tok, "provskylt") or approx_prefix(tok, "skyltarna")
                or approx_prefix(tok, "rekkareit")):
            leg0["needsPlates"] = True
            break

    for sc in [x for s in stripped for x in s.split(",")]:
        fsc = fold_ascii(sc)
        in_boot = has_any_stem(fsc, ["boot", "back"], ["takakont", "tavaratil", "kontissa", "takapenk", "kyydis", "trunk", "bakluck",
                                                       "bagag", "foljer", "vanteineen", "vanteilla", "mukaan"]) or bool(_I_BILEN.search(fsc))
        if in_boot:
            continue
        if has_any_stem(fsc, [], ["kesarenk", "kesareng", "sommardack"]) or (
                has_any_stem(fsc, [], ["summer"]) and has_any_stem(fsc, [], ["tyres", "tires"])):
            leg0["summerTyres"] = True

    for clause in clauses:
        _, _, raw_clean = split_correction(clause)
        fc = fold_ascii(raw_clean)

        if has_any_stem(fc, [], ["myyja", "saljar", "seller"]) and has_any_stem(fc, ["home"], ["kotona", "paikalla", "hemma"]):
            continue

        if has_any_stem(fc, ["pays"], ["maksu", "maksaa", "maksettu", "rahoitus", "payment", "betalning"]):
            t = extract_day_and_clock(clause, request["arrivedAt"])
            if t is not None:
                leg0["releasedAt"] = t if leg0["releasedAt"] is None else max(leg0["releasedAt"], t)
            continue

        is_customer_pickup = ((has_any_stem(fc, [], ["asiakas", "customer", "kunden"]) and has_any_stem(fc, [], ["hakemaan", "noutaa", "hamtar", "perill", "there"]))
                              or bool(_MUST_THERE.search(fc)) or bool(_MASTE.search(fc)))
        is_delivery_deadline = (is_customer_pickup or bool(_SKA.search(fc))
                                or (has_any_stem(fc, [], ["perill", "perille", "toimit", "framme", "destin", "arriv", "deliver"])
                                    and (has_any_stem(fc, ["viim", "by"], ["viimeist", "menness", "senast", "latest", "later"])
                                         or bool(_NO_LATER.search(fc)) or bool(_MUST_ARRIVE.search(fc)))))
        if is_delivery_deadline and not has_any_stem(fc, ["asti"], ["vastaanot"]):
            dl = extract_day_and_clock(clause, request["arrivedAt"])
            if dl is not None and dl < max_option_deadline:
                last_leg["noteDeadline"] = dl if last_leg["noteDeadline"] is None else min(last_leg["noteDeadline"], dl)
                leg0["noteDeadline"] = dl if leg0["noteDeadline"] is None else min(leg0["noteDeadline"], dl)
            continue

        fc_tokens = tokenize_folded(raw_clean)
        has_kohde = any(t == "kohde" or t.startswith("kohte") for t in fc_tokens)
        is_delivery_hours = (has_kohde or has_any_stem(fc, [], ["vastaanot", "toimitusosoit", "mottag", "receiv", "destin"])
                             or (has_any_stem(fc, [], ["perill"]) and (extract_range(raw_clean) is not None
                                                                        or has_any_stem(fc, ["auki", "asti"], ["kiinni", "ketaan", "sulke"]))))
        if is_delivery_hours:
            if last_leg["deliveryHours"] and not req_last_leg["delivery"]["privateAddress"]:
                rng = extract_range(raw_clean)
                if rng:
                    last_leg["deliveryHours"]["opens"] = max(last_leg["deliveryHours"]["opens"], rng["opens"])
                    last_leg["deliveryHours"]["closes"] = min(last_leg["deliveryHours"]["closes"], rng["closes"])
                else:
                    close_min = extract_corrected_minutes(clause)
                    if close_min is not None:
                        last_leg["deliveryHours"]["closes"] = min(last_leg["deliveryHours"]["closes"], close_min)
            continue

        rng = extract_range(raw_clean)
        if rng:
            if leg0["pickupHours"] and not req_leg0["pickup"]["privateAddress"]:
                leg0["pickupHours"]["opens"] = max(leg0["pickupHours"]["opens"], rng["opens"])
                leg0["pickupHours"]["closes"] = min(leg0["pickupHours"]["closes"], rng["closes"])
            continue

        is_not_before = bool(_NOT_BEFORE.search(fc.replace("'", "")))
        is_pickup_close = (not is_not_before) and (
            has_any_stem(fc, [], ["saakka", "until", "sulke", "stang", "kiinni", "closes", "ketaan"])
            or bool(_WE_CLOSE.search(fc)) or bool(_SHOP_CLOSE.search(fc)) or bool(_INGEN.search(fc)) or bool(_EI_ENAA.search(fc))
            or (has_any_stem(fc, ["haku"], ["nouto", "haettav", "hakea", "hamta", "hamtning", "collect", "pick", "pickup"])
                and (has_any_stem(fc, ["fore"], ["ennen", "before", "viimeist", "senast"]) or bool(_NO_LATER.search(fc)))))
        if is_pickup_close:
            close_min = extract_corrected_minutes(clause)
            if close_min is not None and leg0["pickupHours"] and not req_leg0["pickup"]["privateAddress"]:
                leg0["pickupHours"]["closes"] = min(leg0["pickupHours"]["closes"], close_min)
            continue

        if has_any_stem(fc, ["heti", "now", "away", "direkt"], ["pihalla"]) and extract_clock_minutes(raw_clean) is None:
            continue

        is_ready = (is_not_before
                    or has_any_stem(fc, ["klar", "ready"], ["valmi", "noudettav", "haettav", "alkaen", "aikaisint", "tidigast", "framat",
                                                            "earliest", "huolto", "huollt", "holto", "pesu", "odottaa", "worksh"])
                    or bool(_VOI_NOUTAA.search(fc)))
        if is_ready:
            t = extract_day_and_clock(clause, request["arrivedAt"])
            if t is not None:
                leg0["readyAt"] = max(leg0["readyAt"], t)
    return legs
