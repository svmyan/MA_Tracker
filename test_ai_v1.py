import os
from google import genai
import re
import feedparser
from google.genai import types

MODEL = "gemini-3.1-flash-lite"
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

URL = "https://www.globenewswire.com/en/AtomFeed/subjectcode/27-Mergers%20And%20Acquisitions/feedTitle/GlobeNewswire%20-%20Mergers%20And%20Acquisitions"
AGENT = "Mozilla/5.0 (compatible; MA-Tracker personal project)"
RULES = """Use ONLY the text or page given. Do not use outside knowledge and do not guess.
Write 1 to 2 plain sentences on the strategic rationale and any synergies it states.
If it does not state them, say "Rationale not stated."
No headers, bullets, bold, or preamble."""

# grab the newest deal from the feed
feed = feedparser.parse(URL, agent=AGENT)
entry = feed.entries[0]
title = entry.title
link = entry.link
summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")) # strips HTML tags 

print("DEAL:", title)
print("SUMMARY:", summary)
print()

# let Gemini read the link 
prompt = f"You write short notes for an M&A deal tracker. \nRead this press release: {link}\n{RULES}"
r2 = client.models.generate_content(
    model = MODEL,
    contents = prompt,
    config = types.GenerateContentConfig(tools=[{"url_context": {}}]),
)

print("OUTPUT (URL context):")
print(r2.text)
print()
print("FETCH STATUS:", getattr(r2.candidates[0], "url_context_metadata", None))
