# purpose is to create a tracker for M&A activity in north america
from datetime import datetime
from zoneinfo import ZoneInfo
from calendar import timegm
import feedparser
import json
import os
import re
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
    "Business Wire":"https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeEFtRWA==",
    "PR Newswire": "https://www.prnewswire.com/rss/financial-services-latest-news/acquisitions-mergers-and-takeovers-list.rss",
}

# AI integration variables
MODELS = ["gemini-3.1-flash-lite", "gemini-2.5-flash-lite"] 
MAX_NOTES_PER_RUN = int(os.environ.get("MAX_NOTES", 60))
INDUSTRIES = ["Technology", "Healthcare", "Financials", "Energy", "Industrials",
              "Consumer", "Real Estate", "Materials", "Telecom & Media", "Other"]
COUNTRY_NAMES = {"US": "United States", "CA": "Canada", "Other": "International"}
RULES = f"""Use ONLY the text or page given. Do not use outside knowledge and do not guess.
Reply in exactly this format, 7 parts separated by |:
Industry | Country | Acquirer | Target | Deal value | Funding | Rationale
1. Industry: the target company's industry, picked from exactly this list: {", ".join(INDUSTRIES)}.
2. Country: where the target company is headquartered. Write US, CA, or Other. If unclear, write Other.
3. Acquirer: the company buying, or the first company named in a merger. Company name only. If unclear, write Not stated.
4. Target: the company being bought, merged with, or sold off. Company name only. If unclear, write Not stated.
5. Deal value: the total value as a number in millions plus currency code, like 1200 USD or 85.5 CAD. If the page does not state a value, write Undisclosed.
6. Funding: how it is paid for, like Cash 60%, Stock 40% or All cash. If not stated, write Not stated.
7. Rationale: 1 to 2 plain sentences on the strategic rationale and any synergies it states. If it does not state them, write Rationale not stated.
No headers, bullets, bold, or preamble."""

api_key = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=api_key) if api_key else None

# phrases to filter for actual deal announcement
DEAL_WORDS = ["to acquire", "acquisition of", "acquires", "to merge", "merger", "definitive agreement", "spinoff", "spin-off", "divestiture", "to split"]
CLOSED_WORDS = ["completes", "completed", "closes","closing of"]
TROUBLE_WORDS = ["rejects", "terminat"]
SKIP_WORDS = ["form 8.3"]

# search for keywords, a match has to start at the beginning of a word (so "discloses" does not match "closes")
def has_any(words, text):
    return any(re.search(r"\b" + re.escape(word), text) for word in words)

def classify(title):
    title = title.lower()
    if not has_any(DEAL_WORDS, title) or has_any(SKIP_WORDS, title):    # ignores not M&A announcements 
        return None                                                     
    if has_any(TROUBLE_WORDS, title):                                   # returns disputed deals
        return "DISPUTE" 
    if has_any(CLOSED_WORDS, title):                                    # returns closed deals
        return "CLOSED"
    return "ANNOUNCED"

# time zone converter 
def nice_date(text):
    try:
        utc_time = datetime.fromisoformat(text)
        local = utc_time.astimezone(ZoneInfo("America/Toronto"))
        return local.strftime("%b %d, %Y, %I:%M %p")
    except Exception as e:
        print("date error:", e)
        return text.replace("T", " ").replace("Z", "")

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

    new_deals = []
    for entry in feed.entries:
        link = entry.link
        if source == "Business Wire":
            link = link.split("?")[0]
        status = classify(entry.title)
        if status and link not in seen_links and entry.title not in seen_links:
            if entry.get("published_parsed"):
                date = datetime.fromtimestamp(timegm(entry.published_parsed), tz=ZoneInfo("UTC")).isoformat()
            else:
                date = entry.get("published", entry.get("updated", "no date"))
            new_deals.append({
                "title": entry.title,
                "status": status,
                "source": source,
                "date": date,
                "link": link,
            })
            seen_links.add(link)
            seen_links.add(entry.title)
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

def stat_box(number, label, status=None):
    if status:
        return f'<button class="stat" data-status="{status}"><b>{number}</b><span>{label}</span></button>'
    return f'<div class="stat"><b>{number}</b><span>{label}</span></div>'

def count_status(deals, status):
    return sum(1 for d in deals if d["status"] == status)

def money(size):
    if size >= 1000:
        return f"${size / 1000:.1f}B"
    return f"${size:,.0f}M"

def format_size(deal):
    if "size_musd" not in deal:
        return "Pending"
    if deal["size_musd"] is None:
        return "Undisclosed"
    return money(deal["size_musd"])

def party(deal, key):
    if key not in deal:
        return "Pending"
    return escape(deal[key] or "Not stated", quote=True)

def deal_card(deal):
    status = deal["status"]
    title = escape(deal["title"])
    link = deal["link"]
    deal_id = escape(link, quote=True)
    source = deal.get("source", "unknown")
    date = nice_date(deal["date"])
    industry = escape(deal.get("industry") or "Other", quote=True)
    notes = escape(deal.get("notes", ""))
    size = format_size(deal)
    funding = escape(deal.get("funding") or "Not stated")
    acquirer = party(deal, "acquirer")
    target = party(deal, "target")
    size_raw = deal.get("size_musd")
    size_data = "" if size_raw is None else size_raw
    search = escape(f"{deal['title']} {deal.get('acquirer') or ''} {deal.get('target') or ''}".lower(), quote=True)
    country = deal.get("country")
    country_data = country if country in COUNTRY_NAMES else ""
    country_html = f'<span class="country">{COUNTRY_NAMES[country]}</span>' if country_data else ""
    if notes:
        notes_html = f'<div class="notes">{notes}</div>'
    else:
        notes_html = '<div class="notes pending">AI overview unavailable right now. It will retry on the next update.</div>'
    return f"""
    <div class="deal" data-deal-id="{deal_id}" data-industry="{industry}" data-status="{status}" data-size="{size_data}" data-country="{country_data}" data-search="{search}">
        <div class="card">
            <span class="tag UNSEEN" hidden>NEW</span>
            <span class="tag {status}">{status}</span>
            {country_html}
            <a href ="{link}" target="_blank">{title}</a>
            {notes_html}
            <div class="meta">{source} &middot; {industry} &middot; {date}</div>
        </div>
        <div class="side">
            <div class="size-card">
                <div class="size-label">Deal size</div>
                <div class="size-value">{size}</div>
                <div class="size-funding">{funding}</div>
            </div>
            <div class="parties-card">
                <div class="party"><span class="party-label">Buyer</span><span class="party-name" title="{acquirer}">{acquirer}</span></div>
                <div class="party"><span class="party-label">Target</span><span class="party-name" title="{target}">{target}</span></div>
            </div>
        </div>
    </div>"""

def filter_buttons():
    out = '<button class="filter active" data-industry="All">All</button>'
    for ind in INDUSTRIES:
        out += f'<button class="filter" data-industry="{escape(ind, quote=True)}">{escape(ind)}</button>'
    return out

def build_page(deals):
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        page = f.read()

    cards = "".join(deal_card(d) for d in reversed(deals))
    total = sum(d.get("size_musd") or 0 for d in deals)
    stats = (
        stat_box(len(deals), "total tracked", "All")
        + stat_box(count_status(deals, "ANNOUNCED"), "Announced", "ANNOUNCED")
        + stat_box(count_status(deals, "CLOSED"), "Closed", "CLOSED")
        + stat_box(count_status(deals, "DISPUTE"), "Disputes", "DISPUTE")
        + stat_box(money(total), "Total disclosed")
    )
    updated = datetime.now(ZoneInfo("America/Toronto")).strftime("%b %d, %Y, %I:%M %p")
    html = (page.replace("STATS_HERE", stats)
            .replace("FILTERS_HERE", filter_buttons())
            .replace("CARDS_HERE", cards)
            .replace("UPDATED_HERE", updated))
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

# convert numbers to USD millions
CAD_TO_USD = 0.73 # rough rate, update now and then 

# only USD and CAD are handled, any other currency comes back as None (shown as Undisclosed)
def parse_value(raw):
    try:
        num, cur = raw.replace(",", "").split()
        num = float(num)
    except ValueError:
        return None
    cur = cur.upper()
    if cur == "USD":
        return round(num, 1)
    if cur == "CAD":
        return round(num * CAD_TO_USD, 1)
    return None

# Gemini AI integration
def make_notes(deal):
    if client is None:
        return None
    prompt = f"You write short notes for an M&A deal tracker.\nRead this press release: {deal['link']}\n{RULES}"
    try:
        response = None
        for model in MODELS:
            for attempt in range(2):
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(tools=[{"url_context": {}}]),
                    )
                    break
                except Exception as e:
                    if "503" in str(e) or "UNAVAILABLE" in str(e):
                        print("busy, retrying", model, deal["title"])
                        time.sleep(15 * (attempt + 1))
                    else:
                        raise
            if response is not None:
                break

        if response is None:
            return None

        meta = response.candidates[0].url_context_metadata
        read_ok = bool(meta and meta.url_metadata and "SUCCESS" in str(meta.url_metadata[0].url_retrieval_status))
        if not read_ok:
            print("page not read", deal["title"])
            return None

        text = " ".join((response.text or "").split())
        parts = [p.strip() for p in text.split("|", 6)]
        if len(parts) == 7:
            industry, country, acquirer, target, value, funding, notes = parts
        else:
            industry, country, acquirer, target, value, funding, notes = "Other", "Other", "Not stated", "Not stated", "Undisclosed", "Not stated", text
        if industry not in INDUSTRIES:
            industry = "Other"
        country = country.upper() if country.upper() in ("US", "CA") else "Other"
        return {
            "industry": industry,
            "country": country,
            "acquirer": None if acquirer.lower().startswith("not stated") else acquirer,
            "target": None if target.lower().startswith("not stated") else target,
            "size_musd": parse_value(value),
            "funding": None if funding.lower().startswith("not stated") else funding,
            "notes": notes,
        }
    except Exception as e:
        print("note error:", e)
        return None
    
# function adds the AI notes to the site 
def add_notes(deals):
    if client is None:
        return
    tried = 0
    for deal in reversed(deals):
        if "notes" in deal and "size_musd" in deal and "target" in deal and "country" in deal:
            continue
        if tried >= MAX_NOTES_PER_RUN:
            break
        result = make_notes(deal)
        if result:
            deal.update(result)
        tried += 1
        time.sleep(5)

# runs the process
def main():
    old_deals = load_deals()
    for deal in old_deals:
        if deal.get("status") == "NEW":
            deal["status"] = "ANNOUNCED"
    seen_links = {d["link"] for d in old_deals} | {d["title"] for d in old_deals}
    new_deals =[]

    for source, url in FEEDS.items():
        new_deals.extend(get_new_deals(source, url, seen_links))
        new_deals.sort(key=lambda d: d["date"])

    show_section("JUST ADDED", new_deals)
    show_section("EARLIER DEALS", list(reversed(old_deals))[:SHOW_OLD])

    all_deals = old_deals + new_deals
    add_notes(all_deals)
    save_deals(all_deals)
    build_page(all_deals)
    print(f"{len(new_deals)} new deals added, {len(all_deals)} total saved.")

main()