# purpose is to create a tracker for M&A activity in north america
from datetime import datetime
from zoneinfo import ZoneInfo
import feedparser
import json
import os

# feed address (GlobeNewsWire M&A Category) and ID badge so site doesn't block the code 
url = "https://www.globenewswire.com/en/AtomFeed/subjectcode/27-Mergers%20And%20Acquisitions/feedTitle/GlobeNewswire%20-%20Mergers%20And%20Acquisitions"
agent = "Mozilla/5.0 (compatible; MA-Tracker personal project)"
FILE = "deals.json"

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

# load deals saved on earlier runs, if there's no file it starts it as an empty list
if os.path.exists(FILE):
    with open(FILE, "r", encoding="utf-8") as f: # f is a nickname for the open file, with closes the file when the indented code finishes 
        deals = json.load(f)                     
else:
    deals = []

seen_links = [d["link"] for d in deals]

feed = feedparser.parse(url, agent = agent) #download the feed
new_count = 0

for entry in feed.entries:                                              # checks deal status before printing
    status = classify(entry.title)
    if status and entry.link not in seen_links:                          
        deal = {                                                        # status dictionary
            "title": entry.title,
            "status": status,
            "date": entry.get("published", entry.get("updated", "no date")),
            "link": entry.link,
        }
        deals.append(deal)
        new_count += 1
        print(f"[{status}] {entry.title}")
        print(nice_date(deal["date"]))
        print(deal["link"])
        print()
    
# save everything back to the file 
with open(FILE, "w", encoding="utf-8") as f:
    json.dump(deals, f, indent = 2)

print(f"{new_count} new deals added, {len(deals)} total saved.")