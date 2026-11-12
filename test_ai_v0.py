import os
from google import genai

MODEL = "gemini-3.5-flash-lite"
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
response = client.models.generate_content(
    model=MODEL,
    contents="what are the synergies and rationale behind this deal: Intermex Rejects Western Union’s Purported Termination of Merger Agreement",
)
print(response.text)