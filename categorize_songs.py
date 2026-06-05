"""
Reads liked_songs.json, uses Claude to intelligently group songs into playlists,
and writes a detailed markdown report + machine-readable JSON plan.
"""

import json
import os
import re
import sys
import time
from dotenv import load_dotenv
import anthropic
from tqdm import tqdm

load_dotenv()

INPUT_FILE = "liked_songs.json"
REPORT_FILE = "playlist_plan.md"
JSON_PLAN_FILE = "playlist_plan.json"

# Claude processes songs in batches to stay within context limits
BATCH_SIZE = 50


def load_songs():
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: {INPUT_FILE} not found. Run fetch_songs.py first.")
        sys.exit(1)
    with open(INPUT_FILE, encoding="utf-8") as f:
        return json.load(f)


def song_summary(song):
    """Compact single-line summary for sending to Claude."""
    af = song.get("audio_features", {})
    energy = af.get("energy")
    valence = af.get("valence")
    danceability = af.get("danceability")
    acousticness = af.get("acousticness")
    tempo = af.get("tempo")
    genres = ", ".join(song.get("genres", [])[:5]) or "unknown"
    release = song.get("release_date", "")[:4] or "?"
    artists = ", ".join(song.get("artists", []))
    return (
        f'ID:{song["id"]} | "{song["name"]}" by {artists} | '
        f"year:{release} | genres:[{genres}] | "
        f"energy:{energy:.2f} valence:{valence:.2f} dance:{danceability:.2f} "
        f"acoustic:{acousticness:.2f} bpm:{tempo:.0f}"
        if all(v is not None for v in [energy, valence, danceability, acousticness, tempo])
        else f'ID:{song["id"]} | "{song["name"]}" by {artists} | year:{release} | genres:[{genres}]'
    )


SYSTEM_PROMPT = """You are a music curator with deep knowledge of genres, eras, moods, and cultural contexts across world music.

You will receive a list of songs with metadata (audio features, genres, release year) and must group them into meaningful playlists.

Categorisation axes to consider (use whichever make sense for the actual songs):
- **Language / Region**: Hindi/Bollywood, Tamil/Kollywood, Telugu, Punjabi, English, K-pop, Latin, etc.
- **Era**: 90s nostalgia, 2000s hits, Modern (2020s), Classic Rock era, etc.
- **Mood**: Sad/Melancholic, Happy/Upbeat, Romantic, Angry/Intense, Peaceful/Calm
- **Energy/Vibe**: Party bangers, Chill & Lo-fi, Workout/Gym, Late-night drive, Morning coffee
- **Genre**: Hip-hop, R&B, Pop, Rock, Electronic/EDM, Jazz, Classical, Metal, Indie, Folk
- **Occasion**: Road trip, Study/Focus, Heartbreak, Hype/Motivation, Background music
- **Fusion combos**: e.g. "Bollywood Sad Classics", "Tamil Workout Bangers", "English Indie Chill"

Rules:
1. Every song must appear in EXACTLY ONE playlist
2. Playlist names should be evocative and specific (not just "Pop" — better: "2000s Pop Nostalgia")
3. Aim for playlists of 10–50 songs. Avoid micro-playlists (<5 songs) — merge small groups
4. If a song doesn't fit neatly, put it in the closest playlist and note it
5. Use the song ID as the unique identifier

Respond ONLY with a JSON object (no markdown fences) in this exact format:
{
  "playlists": [
    {
      "name": "Playlist Name",
      "description": "One sentence describing the vibe/theme",
      "tags": ["tag1", "tag2"],
      "songs": ["song_id_1", "song_id_2", ...]
    }
  ]
}"""


def categorize_batch(client, songs, batch_index, total_batches, existing_playlists=None):
    """Send a batch to Claude for categorization."""
    song_lines = "\n".join(song_summary(s) for s in songs)

    context = ""
    if existing_playlists:
        playlist_names = [p["name"] for p in existing_playlists]
        context = (
            f"\nExisting playlists from previous batches (you can assign songs to these OR create new ones):\n"
            + "\n".join(f"- {name}" for name in playlist_names)
            + "\n"
        )

    user_message = (
        f"Batch {batch_index + 1}/{total_batches}. Categorise these {len(songs)} songs into playlists.\n"
        f"{context}\n"
        f"Songs:\n{song_lines}"
    )

    for attempt in range(5):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
            )
            break
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 4:
                wait = 30 * (attempt + 1)
                print(f"\n  API overloaded, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    raw = response.content[0].text.strip()
    # strip markdown fences if Claude wraps anyway
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def merge_batch_results(all_batch_results, songs_by_id):
    """
    Merge batched playlist results, combining playlists with the same name
    and resolving duplicate song assignments.
    """
    merged = {}  # name -> playlist dict
    song_assigned = {}  # song_id -> playlist_name (first assignment wins)

    for batch in all_batch_results:
        for playlist in batch.get("playlists", []):
            name = playlist["name"]
            if name not in merged:
                merged[name] = {
                    "name": name,
                    "description": playlist.get("description", ""),
                    "tags": playlist.get("tags", []),
                    "songs": [],
                }
            for sid in playlist.get("songs", []):
                if sid not in song_assigned:
                    song_assigned[sid] = name
                    merged[name]["songs"].append(sid)

    # catch any songs that didn't get assigned (shouldn't happen but defensive)
    unassigned = [s["id"] for s in songs_by_id.values() if s["id"] not in song_assigned]
    if unassigned:
        if "Uncategorised" not in merged:
            merged["Uncategorised"] = {
                "name": "Uncategorised",
                "description": "Songs that didn't fit into other playlists",
                "tags": ["misc"],
                "songs": [],
            }
        merged["Uncategorised"]["songs"].extend(unassigned)

    # remove empty playlists
    return [p for p in merged.values() if p["songs"]]


def run_final_consolidation(client, playlists, songs_by_id):
    """
    Ask Claude to review and consolidate the merged playlists — merge tiny ones,
    rename for clarity, rebalance if needed. This is a lightweight metadata pass
    (no song reassignment, just playlist-level cleanup).
    """
    playlist_summaries = []
    for p in playlists:
        playlist_summaries.append(
            {
                "name": p["name"],
                "description": p["description"],
                "tags": p["tags"],
                "song_count": len(p["songs"]),
                "sample_songs": [
                    f'"{songs_by_id[sid]["name"]}" by {", ".join(songs_by_id[sid]["artists"])}'
                    for sid in p["songs"][:5]
                    if sid in songs_by_id
                ],
            }
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[
            {
                "role": "user",
                "content": (
                    "Review these playlists created from a user's liked songs. "
                    "Suggest improvements: better names, merge tiny playlists (<5 songs) into nearest fit, "
                    "split any that are too large and generic (>80 songs). "
                    "Return ONLY a JSON object (no fences) with this structure:\n"
                    '{"suggestions": [{"action": "rename|merge|split|keep", "playlist": "current name", '
                    '"new_name": "...", "reason": "...", "merge_into": "..."}]}\n\n'
                    f"Playlists:\n{json.dumps(playlist_summaries, indent=2)}"
                ),
            }
        ],
    )
    raw = response.content[0].text.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    return json.loads(raw)


def apply_consolidation(playlists, suggestions):
    """Apply rename/merge suggestions from Claude."""
    pl_map = {p["name"]: p for p in playlists}

    for s in suggestions.get("suggestions", []):
        action = s.get("action")
        pl_name = s.get("playlist")
        if pl_name not in pl_map:
            continue

        if action == "rename" and s.get("new_name"):
            pl_map[pl_name]["name"] = s["new_name"]
            pl_map[s["new_name"]] = pl_map.pop(pl_name)

        elif action == "merge" and s.get("merge_into"):
            target = s["merge_into"]
            if target in pl_map:
                pl_map[target]["songs"].extend(pl_map[pl_name]["songs"])
                del pl_map[pl_name]

    return list(pl_map.values())


def write_markdown_report(playlists, songs_by_id, output_file):
    total_songs = sum(len(p["songs"]) for p in playlists)
    lines = [
        "# Spotify Liked Songs — Playlist Organisation Plan",
        "",
        f"**Total songs analysed:** {total_songs}  ",
        f"**Playlists proposed:** {len(playlists)}",
        "",
        "---",
        "",
        "## Summary",
        "",
        "| Playlist | Songs | Tags | Description |",
        "|----------|-------|------|-------------|",
    ]
    for p in sorted(playlists, key=lambda x: -len(x["songs"])):
        tags = ", ".join(p.get("tags", []))
        desc = p.get("description", "").replace("|", "\\|")
        lines.append(f'| **{p["name"]}** | {len(p["songs"])} | {tags} | {desc} |')

    lines += ["", "---", "", "## Playlists in Detail", ""]

    for p in sorted(playlists, key=lambda x: -len(x["songs"])):
        lines.append(f'### {p["name"]} ({len(p["songs"])} songs)')
        lines.append("")
        if p.get("description"):
            lines.append(f'*{p["description"]}*')
            lines.append("")
        if p.get("tags"):
            lines.append("**Tags:** " + " · ".join(f"`{t}`" for t in p["tags"]))
            lines.append("")
        lines.append("| # | Song | Artist | Year | Genres |")
        lines.append("|---|------|--------|------|--------|")
        for i, sid in enumerate(p["songs"], 1):
            song = songs_by_id.get(sid)
            if not song:
                continue
            name = song["name"].replace("|", "\\|")
            artists = ", ".join(song["artists"]).replace("|", "\\|")
            year = (song.get("release_date") or "")[:4] or "?"
            genres = ", ".join(song.get("genres", [])[:3]) or "—"
            lines.append(f"| {i} | {name} | {artists} | {year} | {genres} |")
        lines.append("")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    print("Loading songs from", INPUT_FILE)
    songs = load_songs()
    songs_by_id = {s["id"]: s for s in songs}
    print(f"Loaded {len(songs)} songs")

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Split into batches
    batches = [songs[i : i + BATCH_SIZE] for i in range(0, len(songs), BATCH_SIZE)]
    print(f"Processing in {len(batches)} batches of up to {BATCH_SIZE} songs each...")

    all_batch_results = []
    existing_playlists = []
    for i, batch in enumerate(tqdm(batches, desc="Categorising batches")):
        result = categorize_batch(client, batch, i, len(batches), existing_playlists)
        all_batch_results.append(result)
        existing_playlists = merge_batch_results(all_batch_results, songs_by_id)

    print("Merging batch results...")
    playlists = merge_batch_results(all_batch_results, songs_by_id)
    print(f"  → {len(playlists)} playlists before consolidation")

    print("Running consolidation pass with Claude...")
    suggestions = run_final_consolidation(client, playlists, songs_by_id)
    playlists = apply_consolidation(playlists, suggestions)
    print(f"  → {len(playlists)} playlists after consolidation")

    # Save JSON plan
    plan = {"playlists": playlists}
    with open(JSON_PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"Saved JSON plan to {JSON_PLAN_FILE}")

    # Write markdown report
    write_markdown_report(playlists, songs_by_id, REPORT_FILE)
    print(f"Saved markdown report to {REPORT_FILE}")

    print("\nDone! Open playlist_plan.md to review the proposed playlists.")
    print("When happy with the plan, run:  python create_playlists.py")


if __name__ == "__main__":
    main()
