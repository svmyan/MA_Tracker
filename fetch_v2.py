# purpose is to create a tracker for M&A activity in north america
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
import json
import os
from html import escape
import time
from google import genai
from google.genai import types

# feed address, ID badge, and other variables
AGENT = "Mozilla/5.0 (compatible; MA-Tracker personal project)"
FILE = "deals.json"
TEMPLATE = "template.html"
SHOW_OLD = 10 # how many earlier deals to display
FEEDS = {
    "GlobeNewswire": "https://www.globenewswire.com/en/AtomFeed/subjectcode/27-Mergers%20And%20Acquisitions/feedTitle/GlobeNewswire%20-%20Mergers%20And%20Acquisitions",
}

# AI integration variables
MODEL = "gemini-3.1-flash-lite"
MAX_NOTES_PER_RUN = 10
RULES = """Use ONLY the text or page given. Do not use outside knowledge and do not guess.
Write 1 to 2 plain sentences on the strategic rationale and any synergies it states.
If it does not state them, say "Rationale not stated."
No headers, bullets, bold, or preamble."""
api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# phrases to filter for actual deal announcement
DEAL_WORDS = ["to acquire", "acquisition of", "acquires", "to merge", "merger", "definitive agreement", "spinoff", "spin-off", "divestiture", "to split"]
CLOSED_WORDS = ["completes", "completed", "closes","closing of"]
TROUBLE_WORDS = ["rejects", "terminat"]
SKIP_WORDS = ["form 8.3"]

def has_any(words, text):
    return any(word in text for word in words)                              # search for keywords

def classify(title):
    title = title.lower()
    if not has_any(DEAL_WORDS, title) or has_any(SKIP_WORDS, title):    # ignores not M&A announcements 
        return None                                                     
    if has_any(TROUBLE_WORDS, title):                                   # returns disputed deals
        return "DISPUTE" 
    if has_any(CLOSED_WORDS, title):                                    # returns closed deals
        return "CLOSED"
    return "NEW"

# time zone converter 
def nice_date(text):
    try:
        utc_time = datetime.fromisoformat(text)
        local = utc_time.astimezone(ZoneInfo("America/Toronto"))
        return local.strftime("%b %d, %Y, %I:%M %p")
    except Exception as e:
        print("date error:", e)
        return text.replace("t", " ").replace("Z", "")

# load deals saved on earlier runs, if there's no file it starts it as an empty list, the tracker's memory
def load_deals():
    if not os.path.exists(FILE):
        return []
    with open(FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# saves deals to the memory list
def save_deals(deals):
    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(deals, f, indent=2)

# downloads feed, checks deals, checks status, classifies each headline, and skips already seen deals
def get_new_deals(source, url, seen_links):
    feed = feedparser.parse(url, agent = AGENT)
    if feed.get("status") != 200:
        print(f"Problem with {source}: status {feed.get('status')}")
        return []

    new_deals =[]
    for entry in feed.entries:
        status = classify(entry.title)
        if status and entry.link not in seen_links:
            new_deals.append({
                "title": entry.title,
                "status": status,
                "source": source,
                "date": entry.get("published", entry.get("updated", "no date")),
                "link": entry.link,
            })
            seen_links.add(entry.link)
    return new_deals

# prints the deal
def show_deal(deal):
    print(f"[{deal['status']}] {deal['title']}")
    print(f"{deal.get('source', 'unknown')} | {nice_date(deal['date'])}")
    print(deal["link"])
    print()

# prints a divider and a header with a count, then calls show_deal on each
def show_section(title, deals):
    print("=" * 60)
    print(f"{title} ({len(deals)})")
    print("=" * 60)
    print()
    if not deals:
        print("none this run")
        print()
    for deal in deals:
        show_deal(deal)

def stat_box(number, label):
    return f'<div class="stat"><b>{number}</b><span>{label}</span></div>'

def count_status(deals, status):
    return sum(1 for d in deals if d["status"] == status)

def deal_card(deal):
    status = deal["status"]
    title = escape(deal["title"])
    link = deal["link"]
    source = deal.get("source", "unknown")
    date = nice_date(deal["date"])
    notes = escape(deal.get("notes", ""))
    notes_html = f'<div class="notes">{notes}</div>' if notes else ""
    return f"""
    <div class="card">
        <span class="tag {status}">{status}</span>
        <a href ="{link}" target="_blank">{title}</a>
        {notes_html}
        <div class="meta">{source} &middot; {date}</div>
    </div>"""

def build_page(deals):
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        page = f.read()

    cards = "".join(deal_card(d) for d in reversed(deals))
    stats = (
        stat_box(len(deals), "total tracked")
        + stat_box(count_status(deals, "NEW"), "New Announcements")
        + stat_box(count_status(deals, "CLOSED"), "Closed")
        + stat_box(count_status(deals, "DISPUTE"), "Disputes")
    )
    updated = datetime.now(ZoneInfo("America/Toronto")).strftime("%b %d, %Y, %I:%M %p")
    html = (page.replace("STATS_HERE", stats)
            .replace("CARDS_HERE", cards)
            .replace("UPDATED_HERE", updated))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

# Gemini AI integration
def make_notes(deal):
    if client is None:
        return ""
    prompt = f"You write short notes for an M&A deal tracker.\nRead this press release: {deal['link']}\n{RULES}"
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(tools=[{"url_context": {}}]),
        )
        meta = response.candidates[0].url_context_metadata
        read_ok = bool(meta and meta.url_metadata and "SUCCESS" in str(meta.url_metadata[0].url_retrieval_status))
        if not read_ok:
            print("page not read", deal["title"])
            return ""
        return " ".join((response.text or "").split())
    except Exception as e:
        print("note error:", e)
        return ""

# function adds the AI notes to the site 
def add_notes(deals):
    tried = 0
    for deal in reversed(deals):
        if deal.get("notes"):
            continue
        if tried >= MAX_NOTES_PER_RUN:
            break
        deal["notes"] = make_notes(deal)
        tried += 1
        time.sleep(5)

# runs the process
def main():
    old_deals = load_deals()
    seen_links = {d["link"] for d in old_deals}
    new_deals =[]

    for source, url in FEEDS.items():
        new_deals.extend(get_new_deals(source, url, seen_links))

    show_section("JUST ADDED", new_deals)
    show_section("EARLIER DEALS", list(reversed(old_deals))[:SHOW_OLD])

    all_deals = old_deals + new_deals
    add_notes(all_deals)
    save_deals(all_deals)
    build_page(all_deals)
    print(f"{len(new_deals)} new deals added, {len(all_deals)} total saved.")

main()