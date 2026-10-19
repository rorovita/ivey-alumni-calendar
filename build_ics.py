#!/usr/bin/env python3
"""Build an iCalendar (.ics) feed of Ivey Alumni events.

Source: the JSON feed behind https://www.ivey.uwo.ca/alumni/events/calendar/
Each event page is read for its "Time:" and "Location:" lines so events get
real start/end times where Ivey lists them; otherwise they are all-day.
"""
import datetime as dt
import html
import json
import re
import sys
import urllib.request
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

BASE = "https://www.ivey.uwo.ca"
API = BASE + "/api/Event/GetEventsByRange/?sites=113336&hideFromCalendar=1&start={start}&end={end}"
CAL_NAME = "Ivey Alumni Events"
UTC = ZoneInfo("UTC")

# Time zone by keyword in the event title (default: Toronto / Eastern).
TZ_RULES = [
    (r"\bB\.?C\.?\b|Vancouver|British Columbia|Whistler", "America/Vancouver"),
    (r"Bay Area|Southern California|San Francisco|Los Angeles", "America/Los_Angeles"),
    (r"Calgary|Alberta|Edmonton", "America/Edmonton"),
    (r"Winnipeg", "America/Winnipeg"),
    (r"New York", "America/New_York"),
    (r"London UK|London, UK|London, England", "Europe/London"),
    (r"Hong Kong", "Asia/Hong_Kong"),
    (r"Singapore", "Asia/Singapore"),
    (r"Beijing|Shanghai", "Asia/Shanghai"),
    (r"India|Mumbai|Delhi", "Asia/Kolkata"),
]
DEFAULT_TZ = "America/Toronto"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (ivey-alumni-calendar feed)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


class TextExtractor(HTMLParser):
    """Turn HTML into text with line breaks at block elements; skips scripts."""
    BLOCKS = {"p", "br", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self.skip = max(0, self.skip - 1)
        elif tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)

    def lines(self):
        text = html.unescape("".join(self.parts)).replace("\xa0", " ").replace("\u200b", "")
        return [re.sub(r"\s+", " ", l).strip() for l in text.split("\n") if l.strip()]


def field(lines, *names):
    pat = re.compile(r"^(?:%s)\s*:\s*(.+)$" % "|".join(names), re.I)
    for l in lines:
        m = pat.match(l)
        if m:
            return m.group(1).strip()
    return None


RANGE_RE = re.compile(
    r"(\d{1,2})(?::(\d{2}))?\s*(?:([ap])\.?\s*m\b\.?)?\s*(?:-|–|—|to|until)\s*"
    r"(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m?\b", re.I)
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([ap])?\.?\s*(?:m\b\.?)?", re.I)


def parse_times(s):
    """'5:30 p.m - 8:00 p.m.' -> ((17,30),(20,0)); end may be None."""
    if not s:
        return None
    s = s.split("(")[0]  # drop "(Doors open ...)" notes
    toks = []
    rng = RANGE_RE.search(s)
    if rng:
        g = rng.groups()
        toks = [[int(g[0]), int(g[1] or 0), (g[2] or "").lower()],
                [int(g[3]), int(g[4] or 0), (g[5] or "").lower()]]
        if any(h > 12 or mi > 59 for h, mi, _ in toks):
            toks = []
    for m in ([] if toks else TIME_RE.finditer(s)):
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
        if not m.group(2) and not ap:
            continue  # bare number, e.g. a date — not a time
        if h > 12 or mi > 59:
            continue
        toks.append([h, mi, ap])
        if len(toks) == 2:
            break
    if not toks:
        return None
    if len(toks) == 2 and not toks[0][2]:
        toks[0][2] = toks[1][2]
        # "11-1pm": start is morning if it would otherwise come after the end
        if toks[0][2] == "p" and toks[0][0] != 12 and toks[0][0] > toks[1][0] and toks[1][0] != 12:
            toks[0][2] = "a"
    out = []
    for h, mi, ap in toks:
        if not ap:
            return None  # can't tell AM/PM — fall back to all-day
        if ap == "p" and h != 12:
            h += 12
        if ap == "a" and h == 12:
            h = 0
        out.append((h, mi))
    return out[0], (out[1] if len(out) > 1 else None)


def tz_for(title, location):
    hay = f"{title} {location or ''}"
    for pat, tz in TZ_RULES:
        if re.search(pat, hay, re.I):
            return tz
    return DEFAULT_TZ


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    out, cur = [], b""
    for ch in line:
        c = ch.encode("utf-8")
        if len(cur) + len(c) > (75 if not out else 74):
            out.append(cur.decode("utf-8"))
            cur = b""
        cur += c
    out.append(cur.decode("utf-8"))
    return "\r\n ".join(out)


def utc(d):
    return d.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def build(events, details):
    now = dt.datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    L = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//ivey-alumni-calendar//EN",
        "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
        f"X-WR-CALNAME:{CAL_NAME}",
        "X-WR-CALDESC:All events from the Ivey Alumni events calendar (ivey.uwo.ca/alumni/events/calendar)\\, refreshed daily.",
        f"X-WR-TIMEZONE:{DEFAULT_TZ}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H", "X-PUBLISHED-TTL:PT6H",
    ]
    for e in sorted(events, key=lambda e: e["start"]):
        url = e["url"] if e["url"].startswith("http") else BASE + e["url"]
        d = details.get(e["id"], {})
        loc, time_s = d.get("location"), d.get("time")
        start_d = dt.date.fromisoformat(e["start"][:10])
        end_d = dt.date.fromisoformat((e.get("end") or e["start"])[:10])
        if end_d <= start_d:
            end_d = start_d + dt.timedelta(days=1)
        times = parse_times(time_s) if (end_d - start_d).days == 1 else None

        desc = [url]
        if time_s:
            desc.append(f"Time: {time_s}")
        if loc:
            desc.append(f"Location: {loc}")
        if e.get("soldOut"):
            desc.append("SOLD OUT")
        desc.append("Details and registration at the link above.")

        L += ["BEGIN:VEVENT", f"UID:ivey-alumni-{e['id']}@ivey-alumni-calendar", f"DTSTAMP:{now}"]
        if times:
            tz = ZoneInfo(tz_for(e["title"], loc))
            s = dt.datetime.combine(start_d, dt.time(*times[0]), tz)
            en = dt.datetime.combine(start_d, dt.time(*times[1]), tz) if times[1] else s + dt.timedelta(hours=2)
            if en <= s:
                en += dt.timedelta(days=1)
            L += [f"DTSTART:{utc(s)}", f"DTEND:{utc(en)}"]
        else:
            L += [f"DTSTART;VALUE=DATE:{start_d:%Y%m%d}", f"DTEND;VALUE=DATE:{end_d:%Y%m%d}",
                  "TRANSP:TRANSPARENT"]
        title = e["title"] + (" (Sold out)" if e.get("soldOut") else "")
        L += [fold(f"SUMMARY:{esc(title)}"), fold(f"URL:{url}"), fold(f"DESCRIPTION:{esc(chr(10).join(desc))}")]
        if loc:
            L.append(fold(f"LOCATION:{esc(loc)}"))
        L.append("END:VEVENT")
    L.append("END:VCALENDAR")
    return "\r\n".join(L) + "\r\n"


def main(out_path="public/ivey-alumni-events.ics"):
    today = dt.date.today()
    start, end = today - dt.timedelta(days=90), today + dt.timedelta(days=540)
    events = json.loads(get(API.format(start=start, end=end)))
    details = {}
    for e in events:
        url = e["url"] if e["url"].startswith("http") else BASE + e["url"]
        try:
            p = TextExtractor()
            p.feed(get(url))
            lines = p.lines()
            details[e["id"]] = {
                "time": field(lines, "time", "when"),
                "location": field(lines, "location", "where", "venue"),
            }
        except Exception as ex:  # one bad page shouldn't break the feed
            print(f"warn: {url}: {ex}", file=sys.stderr)
    if not events:
        sys.exit("No events returned — keeping the previous feed.")
    import os
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(build(events, details))
    print(f"Wrote {len(events)} events to {out_path}")


if __name__ == "__main__":
    main(*sys.argv[1:])
