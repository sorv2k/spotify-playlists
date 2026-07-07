"""
One-shot script: reads playlist_plan.json, finds artist-specific playlists,
asks Claude to reassign their songs into genre/era playlists, saves updated plan.
"""
import json
import os
import re
import anthropic
from dotenv import load_dotenv

load_dotenv()

PLAN_FILE = "playlist_plan.json"

with open(PLAN_FILE, encoding="utf-8") as f:
    plan = json.load(f)

playlists = plan["playlists"]

# Playlists named after specific artists (identified from the plan)
ARTIST_PLAYLIST_NAMES = {
    "The Weeknd: Starboy to After Hours",
    "Juice WRLD: Forever & a Day",
    "Drake's Universe: OVO All-Stars",
    "Post Malone: Rockstar Diary",
    "Metro Boomin Presents: Trap Royalty",
    "Bruno Mars & Friends: Pop Gold",
    "Travis Scott: Astroworld to Utopia",
    "XXXTENTACION: Heartbreak & Darkness",
    "Michael Jackson & Classic Pop Icons",
    "Eminem: Rap God Chronicles",
    "Cigarettes After Sex: Ambient Heartbreak Moods",
}

artist_playlists = [p for p in playlists if p["name"] in ARTIST_PLAYLIST_NAMES]
genre_playlists = [p for p in playlists if p["name"] not in ARTIST_PLAYLIST_NAMES]

genre_summaries = [
    {"name": p["name"], "description": p.get("description", ""), "tags": p.get("tags", [])}
    for p in genre_playlists
]

artist_summaries = [
    {"name": p["name"], "description": p.get("description", ""), "tags": p.get("tags", []), "song_count": len(p["songs"])}
    for p in artist_playlists
]

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

print("Asking Claude to map artist playlists to genre playlists...")
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=2000,
    messages=[{
        "role": "user",
        "content": (
            "I have a set of artist-specific playlists that I want to merge into genre/era playlists. "
            "For each artist playlist, tell me which genre playlist it should merge into.\n\n"
            "Genre playlists:\n"
            + json.dumps(genre_summaries, indent=2)
            + "\n\nArtist playlists to reassign:\n"
            + json.dumps(artist_summaries, indent=2)
            + "\n\nRespond ONLY with a JSON object (no fences):\n"
            '{"assignments": [{"artist_playlist": "...", "merge_into": "..."}]}'
        )
    }]
)

raw = response.content[0].text.strip()
raw = re.sub(r"^```(?:json)?\s*", "", raw)
raw = re.sub(r"\s*```$", "", raw)
assignments = json.loads(raw)["assignments"]

print("Assignments:")
for a in assignments:
    print(f"  {a['artist_playlist']} → {a['merge_into']}")

# Apply merges
pl_map = {p["name"]: p for p in playlists}

for a in assignments:
    src = a["artist_playlist"]
    dst = a["merge_into"]
    if src in pl_map and dst in pl_map:
        pl_map[dst]["songs"].extend(pl_map[src]["songs"])
        del pl_map[src]
    else:
        print(f"  WARNING: could not merge '{src}' → '{dst}' (name mismatch)")

updated_playlists = list(pl_map.values())
print(f"\n{len(playlists)} playlists → {len(updated_playlists)} playlists after merge")

with open(PLAN_FILE, "w", encoding="utf-8") as f:
    json.dump({"playlists": updated_playlists}, f, ensure_ascii=False, indent=2)

print(f"Updated {PLAN_FILE}")
