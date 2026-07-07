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
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from tqdm import tqdm

load_dotenv()

INPUT_FILE = "liked_songs.json"
REPORT_FILE = "playlist_plan.md"
JSON_PLAN_FILE = "playlist_plan.json"
BATCH_SIZE = 30
MIN_PLAYLIST_SIZE = 20
LANGUAGE_PLAYLISTS = {"Dil Ka Playlist", "Pind Vibes", "Namma Naadu", "Kollywood Feels"}


# ---------------------------------------------------------------------------
# Spotify client (used only for re-fetching missing song metadata)
# ---------------------------------------------------------------------------

def get_spotify_client():
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8888/callback"),
            scope="user-library-read",
            open_browser=True,
        )
    )


# ---------------------------------------------------------------------------
# Data loading and cleaning
# ---------------------------------------------------------------------------

def load_songs():
    if not os.path.exists(INPUT_FILE):
        print(f"ERROR: {INPUT_FILE} not found. Run fetch_songs.py first.")
        sys.exit(1)
    with open(INPUT_FILE, encoding="utf-8") as f:
        return json.load(f)


def clean_and_refetch(songs):
    """
    1. Discard songs with no ID (only these are truly unrecoverable).
    2. Re-fetch songs with empty/null name or empty artists array.
    3. Deduplicate by ID, keeping first occurrence.
    Returns (cleaned_songs, stats_dict).
    """
    stats = {"discarded_null_id": 0, "recovered": 0, "duplicates_removed": 0}

    # Step 1: drop songs with no ID
    valid = []
    for s in songs:
        if not s.get("id"):
            stats["discarded_null_id"] += 1
        else:
            valid.append(s)

    # Step 2: re-fetch songs with missing metadata
    needs_refetch = [
        s for s in valid
        if not (s.get("name") or "").strip() or not s.get("artists")
    ]
    if needs_refetch:
        print(f"Re-fetching {len(needs_refetch)} songs with missing name/artists...")
        try:
            sp = get_spotify_client()
            ids = [s["id"] for s in needs_refetch]
            refetch_map = {}
            for i in range(0, len(ids), 50):
                batch_ids = ids[i : i + 50]
                try:
                    result = sp.tracks(batch_ids)
                    for track in result.get("tracks") or []:
                        if track:
                            refetch_map[track["id"]] = track
                    time.sleep(0.1)
                except Exception as e:
                    print(f"  Warning: re-fetch batch failed: {e}")

            for s in needs_refetch:
                track = refetch_map.get(s["id"])
                if track:
                    new_name = track.get("name", "").strip()
                    new_artists = [a["name"] for a in track.get("artists", []) if a.get("name")]
                    if new_name:
                        s["name"] = new_name
                    if new_artists:
                        s["artists"] = new_artists
                    if s.get("name") and s.get("artists"):
                        stats["recovered"] += 1
        except Exception as e:
            print(f"  Warning: Spotify re-fetch skipped ({e})")

    # Step 3: deduplicate by ID (keep first occurrence)
    seen_ids: set = set()
    deduped = []
    for s in valid:
        if s["id"] not in seen_ids:
            seen_ids.add(s["id"])
            deduped.append(s)
        else:
            stats["duplicates_removed"] += 1

    return deduped, stats


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a music curator classifying songs into these 16 playlists.

## THE 16 PLAYLISTS

1. Dil Ka Playlist — Hindi/Bollywood songs
2. Pind Vibes — Punjabi songs
3. Namma Naadu — Kannada songs
4. Kollywood Feels — Tamil songs
5. Run the Trap — Hip-hop and rap (all languages)
6. Feel Good Pop — Mainstream Western pop (upbeat, radio-friendly)
7. 2 AM Feels — Sad/emotional songs (all languages)
8. Pre-game Bangers — Party/hype songs (all languages)
9. Nostalgia Mode — Classics and throwbacks (pre-2012 era feel)
10. Sunday Morning — Chill/mellow/low-energy songs (all languages)
11. Beast Mode — Workout/aggressive/high-tempo songs
12. Main Aur Tum — Romantic love songs (all languages)
13. Electronic & EDM: Festival to Late Night — EDM, house, electronic dance
14. Alternative & Rock Anthems — Rock, alternative, indie rock, grunge
15. Global Anthems: World Music & Feel-Good Hymns — World music, global feel-good
16. Wildcard Mix — Anything that genuinely doesn't fit elsewhere

---

## MULTI-PLAYLIST RULE (important)

Classification is NOT mutually exclusive. Check every song against every playlist independently. If a song qualifies for 3 playlists, add it to all 3. A Punjabi sad song goes into both Pind Vibes AND 2 AM Feels. A Bollywood workout song goes into Dil Ka Playlist AND Beast Mode. Every song must appear in AT LEAST ONE playlist.

No duplicates within a single playlist — a song ID should appear at most once per playlist, but can appear in multiple playlists.

---

## CLASSIFICATION RULES

### Language playlists (1–4) — check these first for Indian music

**Dil Ka Playlist (Hindi/Bollywood)**
Artists: Pritam, Arijit Singh, Vishal-Shekhar, Shankar-Ehsaan-Loy, A.R. Rahman (Hindi work), Mohit Chauhan, KK, Sonu Nigam, Udit Narayan, Alka Yagnik, Kumar Sanu, Lata Mangeshkar, Kishore Kumar, Mukesh, Mohammed Rafi, Shreya Ghoshal (Hindi), Sunidhi Chauhan, Ankit Tiwari, Armaan Malik (Hindi), Amaal Mallik, Mithoon, Sachet-Parampara, Tanishk Bagchi, Vishal Mishra, Jubin Nautiyal, Darshan Raval, Jonita Gandhi, Neha Kakkar, Nakash Aziz, Amit Trivedi, Sachin-Jigar, Salim-Sulaiman, Vishal Dadlani, Anuv Jain, Prateek Kuhad, The Local Train, Zaeden, Ritviz, The Yellow Diary, DIVINE (Hindi tracks — Kaam 25, Apna Time Aayega), Kalyanji-Anandji, Laxmikant-Pyarelal, R.D. Burman, S.D. Burman, Madan Mohan.
Tiebreaker: Hindi title (Kesariya, Khairiyat, Hawayein, Channa Mereya) or Bollywood album (ANIMAL, Brahmastra, Gehraiyaan, Shershaah) → Hindi. Marathi/regional Indian songs → merge here.

**Pind Vibes (Punjabi)**
Artists: AP Dhillon, Karan Aujla, Diljit Dosanjh (almost always Punjabi unless Hindi film), Shubh, Talwiinder, Guru Randhawa, Harrdy Sandhu, Bohemia, Gminxr, Gurinder Gill, Shinda Kahlon, Deep Jandu, Gurnazar, Hasan Raheem, Jaz Dhami, Imran Khan (Pakistani — Bewafa), NDS, Aditya Rikhari.
Yo Yo Honey Singh / Badshah: Punjabi title (Dope Shope, Brown Rang, Blue Eyes) → Punjabi. Bollywood film → Hindi.

**Namma Naadu (Kannada)**
Artists/composers: V. Harikrishna, Raghu Dixit, Vasuki Vaibhav, Vijay Prakash (Kannada), B. Ajaneesh Loknath, Ravi Basrur, Arjun Janya, Chandan Shetty, Sanjith Hegde, Tippu, Puneeth Rajkumar, Sudeep, Rajesh Krishnan, C. Ashwath, Anthony Daasan.
Album signals: KGF Chapter 2, Sapta Sagaradaache Ello, Tagaru, Mr. and Mrs. Ramachari → Kannada.

**Kollywood Feels (Tamil)**
Artists/composers: A.R. Rahman (Tamil work), Harris Jayaraj, Anirudh Ravichander (Tamil films — NOT Jawan/Bollywood), Sid Sriram, S.P. Balasubrahmanyam (Tamil), Bombay Jayashri, Karthik (Tamil playback), G.V. Prakash Kumar, Hesham Abdul Wahab, Clinton Cerejo (Tamil), Sriram Parthasarathy.

**KANNADA — Namma Naadu ONLY.**
Kannada songs must go ONLY into Namma Naadu. Do NOT add them to any mood/genre playlists (2 AM Feels, Sunday Morning, Main Aur Tum, Beast Mode, Pre-game Bangers, etc.). Language identity takes full precedence for Kannada.

**TELUGU — DO NOT classify as Tamil or Hindi.**
Telugu signals: composers S.S. Thaman, M.M. Keeravani, Devi Sri Prasad; films Pushpa, RRR, Baahubali, Saaho, Ala Vaikunthapurramuloo, Arya, Magadheera. Any Telugu song → Wildcard Mix only.

---

### Mood/genre playlists (5–16) — apply independently to every song

**Run the Trap (Hip-hop and Rap)**
All languages. Western: Drake, Travis Scott, Metro Boomin, Kendrick Lamar, Post Malone (rap/trap tracks only — NOT Circles, Sunflower, Mourning), Juice WRLD, XXXTENTACION, Kanye West, J. Cole, Eminem (rap), 21 Savage, Future, Don Toliver, Lil Wayne, Young Thug, Playboi Carti, Gunna, Jack Harlow, Cardi B, Doja Cat (rap), SZA (rap features), Roddy Ricch, Lil Nas X, Ken Carson, DaBaby, Meek Mill, Big Sean, Wiz Khalifa, Snoop Dogg, Ludacris, 50 Cent, Macklemore, Logic, Tech N9ne, Denzel Curry, Jay Rock, Rich Amiri, MGK. Indian: DIVINE, Badshah/YYHS standalone, AP Dhillon/Karan Aujla trap tracks.

**Beast Mode (Workout/High Energy)**
Aggressive, motivational, high-tempo. Eminem (Lose Yourself, Rap God, Berzerk, Not Afraid, Godzilla), Linkin Park (In the End, Numb, New Divide, Crawling — NOT One More Light), Imagine Dragons (Radioactive, Believer, Thunder, Enemy, Bones, Demons), Fall Out Boy (Centuries), Green Day (American Idiot), AC/DC, Aerosmith, Twenty One Pilots (Ride, Heathens), Travis Scott (SICKO MODE, HIGHEST IN THE ROOM, BUTTERFLY EFFECT, MELTDOWN), Kanye (Power, Black Skinhead), Kendrick (HUMBLE., Not Like Us). Indian: DIVINE (Kaam 25, Apna Time Aayega), KGF songs (Toofan, Tagaru Banthu Tagaru), Shankar-Ehsaan-Loy (Zinda).

**Pre-game Bangers (Party)**
Crowd-pleasing, speakers-ready. Bollywood party: Badshah, Yo Yo Honey Singh, Benny Dayal (upbeat), Vishal Dadlani (party), Neha Kakkar, Raftaar, Nucleya. Punjabi party: Karan Aujla hype, Diljit (G.O.A.T., Born to Shine, Naina), Shubh (Still Rollin, Cheques, We Rollin), Guru Randhawa. Western party: LMFAO, Pitbull, DJ Snake, Flo Rida, Jason Derulo, Sean Paul, Chris Brown, Usher, Akon (upbeat), Despacito.
Tiebreaker vs Beast Mode: fun/crowd-pleasing = Pre-game. Aggressive/motivational = Beast Mode.

**2 AM Feels (Sad/Emotional)**
Melancholic, heartbroken, late-night. Western: Juice WRLD (most songs), XXXTENTACION (SAD!, Jocelyn Flores, Moonlight, changes, Hope), Lana Del Rey, Cigarettes After Sex, Powfu (death bed), Trevor Daniel (Falling), Billie Eilish (lovely), Lewis Capaldi, Lord Huron (The Night We Met), Djo (End of Beginning), Noah Kahan, Ruth B., Stephen Sanchez. Bollywood sad: Arijit Singh slow/sad (Agar Tum Saath Ho, Tujhe Kitna Chahne Lage, Channa Mereya, Ae Dil Hai Mushkil, Khairiyat), Atif Aslam slow, KK emotional (Tu Hi Meri Shab Hai, Alvida), Mohit Chauhan (Tum Se Hi). Punjabi sad: Talwiinder, Anuv Jain, Prateek Kuhad, The Local Train, The Yellow Diary.
In love = Main Aur Tum. Heartbreak/loss = 2 AM Feels.

**Main Aur Tum (Romantic)**
Warmth, longing, falling in love — NOT breakup songs. Western: Ed Sheeran (Perfect, Thinking Out Loud, Photograph), John Legend (All of Me), Bruno Mars (That's What I Like, Just The Way You Are), Shawn Mendes + Camila (Señorita), Justin Bieber (Love Yourself, Peaches), Harry Styles (Watermelon Sugar), Ellie Goulding (Love Me Like You Do). Bollywood: Pritam (Hawayein, Kabira, Raabta, Tum Jo Aaye), Arijit romantic (Kesariya, Satranga, Pehla Pyaar), Vishal-Shekhar (Khuda Jaane, Nashe Si Chadh Gayi, Radha). Punjabi: AP Dhillon (With You, Dil Nu, True Stories), Talwiinder (Wishes), Anuv Jain (Husn, Jo Tum Mere Ho), Diljit (Lover, Kinni Kinni).

**Sunday Morning (Chill/Mellow)**
Low tempo, soft production, introspective. Western: Prateek Kuhad, Anuv Jain, Cigarettes After Sex, Powfu, Trevor Daniel, Djo, Stephen Sanchez, Ruth B., Lord Huron, Lewis Capaldi, Passenger (Let Her Go), Keane, Hozier (Too Sweet), Noah Kahan, LAUV, Glass Animals (Heat Waves), AURORA, BoyWithUke (Toxic). Hindi chill: The Local Train (Choo Lo, Aaoge Tum Kabhi), The Yellow Diary, Zaeden, Talwiinder (Khayaal, Dhundhala), Aditya Rikhari (Sahiba, Paro), Ritviz (Udd Gaye). Tamil chill: Sid Sriram (Samajavaragamana, Parayuvaan), Hesham Abdul Wahab (Darshana, Onakka Munthiri).
Exclude anything with fast beat or hype energy.

**Nostalgia Mode (Classics/Throwbacks)**
Pre-2012 era feel. Western classics: Michael Jackson, Eminem (pre-2012), Backstreet Boys, Akon, 50 Cent, Snoop Dogg, Sean Paul, Enrique Iglesias (older), Shakira (Hips Don't Lie, Waka Waka), Coolio, Ludacris, George Michael, Bob Marley, Vengaboys, Boney M., AC/DC, Aerosmith, Green Day, Linkin Park (pre-2012), Queen, Red Hot Chili Peppers, MAGIC!, Sean Kingston. Bollywood classics: Udit Narayan, Alka Yagnik, Kumar Sanu, Lata Mangeshkar, Kishore Kumar, Mukesh, Mohammed Rafi, R.D. Burman, older Shankar-Ehsaan-Loy (Dil Chahta Hai, Kal Ho Na Ho era), older A.R. Rahman (Maahi Ve, Jashn-E-Bahaaraa).

**Feel Good Pop (Mainstream Western Pop)**
Upbeat, radio-friendly Western pop. Taylor Swift (1989, Reputation, Lover, Midnights), Ed Sheeran, Bruno Mars, Dua Lipa, Harry Styles, Olivia Rodrigo (pop tracks), The Weeknd (Blinding Lights, Save Your Tears, Can't Feel My Face), Justin Bieber, Ariana Grande, Charlie Puth, Maroon 5, One Direction, Coldplay, The Chainsmokers, Marshmello, Alan Walker, Calvin Harris, DJ Snake, Major Lazer, Sia, Ellie Goulding, Selena Gomez, Miley Cyrus, Rihanna, Sabrina Carpenter, Tate McRae, Khalid (upbeat), Shawn Mendes, Camila Cabello, ZAYN, Jason Derulo (pop), OneRepublic, Twenty One Pilots (pop), AJR, Tones and I, Gotye, Avicii, David Guetta, Martin Garrix.
Exclude hip-hop artists (Drake, Travis Scott) even if pop-adjacent.

**Electronic & EDM: Festival to Late Night**
Pure EDM, house, trance, electronic dance. Avicii, Marshmello, Martin Garrix, Alan Walker, Calvin Harris, The Chainsmokers, Zedd, Kygo, Hardwell, Skrillex, Daft Punk, Disclosure, Flume, Odesza, Illenium, Deadmau5, Swedish House Mafia, Tiesto.

**Alternative & Rock Anthems**
Rock, alternative, indie rock, grunge, punk. Coldplay, Imagine Dragons, Linkin Park, Green Day, AC/DC, Aerosmith, Fall Out Boy, Paramore, Twenty One Pilots (rock tracks), Arctic Monkeys, The 1975, Tame Impala, Radiohead, Nirvana, Red Hot Chili Peppers, Foo Fighters, Muse, My Chemical Romance, Panic! At The Disco, The Killers, The Strokes, Cage the Elephant.

**Global Anthems: World Music & Feel-Good Hymns**
Uplifting world music, pan-cultural anthems that transcend borders.

**Wildcard Mix**
Songs that genuinely don't fit any other playlist — including all Telugu songs.

---

## GENERAL RULES
1. Check every song against every playlist independently. A song can be in multiple playlists.
2. Every song must appear in AT LEAST ONE playlist.
3. No duplicates within a single playlist (same ID cannot appear twice in the same playlist).
4. Do NOT create any playlists other than the 16 listed above.
5. Telugu songs → Wildcard Mix only. Do not classify them as Tamil or Hindi.
6. Use the song ID as the unique identifier.

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


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def call_claude(client, system, messages, max_tokens=16000):
    for attempt in range(5):
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            break
        except anthropic.APIStatusError as e:
            if e.status_code == 529 and attempt < 4:
                wait = 30 * (attempt + 1)
                print(f"\n  API overloaded, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    def extract(resp):
        if not resp.content:
            return None
        text = resp.content[0].text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        start = text.find("{")
        if start == -1:
            return None
        try:
            obj, _ = json.JSONDecoder().raw_decode(text, start)
            return json.dumps(obj)
        except json.JSONDecodeError:
            return None

    raw = extract(response)
    for attempt in range(3):
        if raw:
            break
        print(f"\n  Empty/invalid response (stop_reason={response.stop_reason}), retrying in 15s...")
        time.sleep(15)
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        raw = extract(response)

    if not raw:
        raise ValueError(f"No valid JSON response after retries (stop_reason={response.stop_reason})")

    return json.loads(raw)


def categorize_batch(client, songs, batch_index, total_batches, existing_playlists=None):
    song_lines = "\n".join(song_summary(s) for s in songs)
    context = ""
    if existing_playlists:
        names = [p["name"] for p in existing_playlists]
        context = (
            "\nPlaylists seen so far (use these names — do not invent new ones):\n"
            + "\n".join(f"- {n}" for n in names)
            + "\n"
        )
    user_message = (
        f"Batch {batch_index + 1}/{total_batches}. Classify these {len(songs)} songs.\n"
        f"{context}\nSongs:\n{song_lines}"
    )
    return call_claude(client, SYSTEM_PROMPT, [{"role": "user", "content": user_message}])


# ---------------------------------------------------------------------------
# Song summary
# ---------------------------------------------------------------------------

def song_summary(song):
    release = (song.get("release_date") or "")[:4] or "?"
    artists = ", ".join(song.get("artists") or [])
    album = song.get("album", "")
    name = song.get("name", "Unknown")
    return f'ID:{song["id"]} | "{name}" by {artists} | album:"{album}" | year:{release}'


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_batch_results(all_batch_results, songs_by_id):
    """
    Merge batched results allowing multi-playlist. Deduplicate within each
    playlist but allow the same song across different playlists.
    """
    merged: dict = {}  # playlist_name -> {name, description, tags, songs: list, _seen: set}

    for batch in all_batch_results:
        for playlist in batch.get("playlists", []):
            name = playlist["name"]
            if name not in merged:
                merged[name] = {
                    "name": name,
                    "description": playlist.get("description", ""),
                    "tags": playlist.get("tags", []),
                    "songs": [],
                    "_seen": set(),
                }
            for sid in playlist.get("songs", []):
                if sid in songs_by_id and sid not in merged[name]["_seen"]:
                    merged[name]["_seen"].add(sid)
                    merged[name]["songs"].append(sid)

    # Ensure every song appears in at least one playlist (fallback: Wildcard Mix)
    all_assigned = {sid for p in merged.values() for sid in p["songs"]}
    unassigned = [s["id"] for s in songs_by_id.values() if s["id"] not in all_assigned]
    if unassigned:
        wc = "Wildcard Mix"
        if wc not in merged:
            merged[wc] = {"name": wc, "description": "Songs that didn't fit other playlists",
                          "tags": ["misc"], "songs": [], "_seen": set()}
        for sid in unassigned:
            if sid not in merged[wc]["_seen"]:
                merged[wc]["_seen"].add(sid)
                merged[wc]["songs"].append(sid)

    # Clean up internal sets
    result = []
    for p in merged.values():
        p.pop("_seen", None)
        if p["songs"]:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------

def write_markdown_report(playlists, songs_by_id, output_file):
    total_assignments = sum(len(p["songs"]) for p in playlists)
    lines = [
        "# Spotify Liked Songs — Playlist Organisation Plan",
        "",
        f"**Total playlist assignments:** {total_assignments}  ",
        f"**Playlists:** {len(playlists)}",
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
        lines.append("| # | Song | Artist | Year |")
        lines.append("|---|------|--------|------|")
        for i, sid in enumerate(p["songs"], 1):
            song = songs_by_id.get(sid)
            if not song:
                continue
            name = (song.get("name") or "").replace("|", "\\|")
            artists = ", ".join(song.get("artists") or []).replace("|", "\\|")
            year = (song.get("release_date") or "")[:4] or "?"
            lines.append(f"| {i} | {name} | {artists} | {year} |")
        lines.append("")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("Loading songs from", INPUT_FILE)
    raw_songs = load_songs()
    print(f"Loaded {len(raw_songs)} songs")

    print("Cleaning and re-fetching missing metadata...")
    songs, clean_stats = clean_and_refetch(raw_songs)
    print(f"  Discarded (null ID):    {clean_stats['discarded_null_id']}")
    print(f"  Duplicates removed:     {clean_stats['duplicates_removed']}")
    print(f"  Recovered via re-fetch: {clean_stats['recovered']}")
    print(f"  Songs for classification: {len(songs)}")

    songs_by_id = {s["id"]: s for s in songs}
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    batches = [songs[i : i + BATCH_SIZE] for i in range(0, len(songs), BATCH_SIZE)]
    print(f"\nProcessing in {len(batches)} batches of up to {BATCH_SIZE} songs each...")

    all_batch_results = []
    existing_playlists: list = []
    for i, batch in enumerate(tqdm(batches, desc="Classifying batches")):
        result = categorize_batch(client, batch, i, len(batches), existing_playlists)
        all_batch_results.append(result)
        existing_playlists = merge_batch_results(all_batch_results, songs_by_id)

    print("Merging all batch results...")
    playlists = merge_batch_results(all_batch_results, songs_by_id)
    print(f"  → {len(playlists)} playlists produced")

    # Apply minimum size threshold (language playlists are always kept)
    final_playlists = []
    skipped_playlists = []
    for p in playlists:
        if p["name"] in LANGUAGE_PLAYLISTS or len(p["songs"]) >= MIN_PLAYLIST_SIZE:
            final_playlists.append(p)
        else:
            skipped_playlists.append(p)

    # Save JSON plan
    plan = {"playlists": final_playlists}
    with open(JSON_PLAN_FILE, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    print(f"Saved JSON plan to {JSON_PLAN_FILE}")

    # Markdown report
    write_markdown_report(final_playlists, songs_by_id, REPORT_FILE)
    print(f"Saved markdown report to {REPORT_FILE}")

    # Terminal summary
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Input songs:             {len(raw_songs)}")
    print(f"  Discarded (null ID):   {clean_stats['discarded_null_id']}")
    print(f"  Duplicates removed:    {clean_stats['duplicates_removed']}")
    print(f"  Recovered via re-fetch:{clean_stats['recovered']}")
    print(f"Songs classified:        {len(songs)}")
    print(f"\nPlaylists created ({MIN_PLAYLIST_SIZE}+ songs, language playlists always included): {len(final_playlists)}")
    for p in sorted(final_playlists, key=lambda x: -len(x["songs"])):
        print(f"  {len(p['songs']):4d}  {p['name']}")
    if skipped_playlists:
        print(f"\nSkipped (< {MIN_PLAYLIST_SIZE} songs): {len(skipped_playlists)}")
        for p in sorted(skipped_playlists, key=lambda x: -len(x["songs"])):
            print(f"  {len(p['songs']):4d}  {p['name']}")
    print("\nDone! Review playlist_plan.md then run: python create_playlists.py")


if __name__ == "__main__":
    main()
