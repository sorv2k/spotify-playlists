"""
One-time script: classifies and adds the 18 songs that were fetched but never
added to playlists in the previous session.
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

load_dotenv()

# IDs of the 18 songs that are in liked_songs.json but not in any playlist
NEW_SONG_IDS = [
    "2A5cwtDZpk7RvsPolrF4UL", "0Y5XxZARngabhUE310PONW", "3s7m0jmCXGcM8tmlvjCvAa",
    "72vuBPMhwFNlSYpTSf6fVD", "0xlWd9o8yjKpJ02WJy79kZ", "464gxyow4GJ7Wuz3cHrdBB",
    "5XsoDbDt98b0FkFLOhsJuS", "1PALLCSlHwAI4upY3sMg8u", "7r6iwgXcR85d9rfqsuf2Af",
    "36N5awamOX6XX5pQn3aFXZ", "1lbNgoJ5iMrMluCyhI4OQP", "6vjpQIdABqntoe3zPazPec",
    "6wsqVwoiVH2kde4k4KKAFU", "3azJifCSqg9fRij2yKIbWz", "75OSVIdR2KPpEmViMt8MX2",
    "3anHs4ijBd3Iw0E0fBPwtH", "364dI1bYnvamSnBJ8JcNzN", "6OY61mofLDKA76sfce1ads",
]

SCOPE = "playlist-modify-public playlist-modify-private playlist-read-private"
ADD_BATCH_SIZE = 100

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
Low tempo, soft production, introspective. Western: Prateek Kuhad, Anuv Jain, Cigarettes After Sex, Powfu, Trevor Daniel, Djo, Stephen Sanchez, Ruth B., Lord Huron, Lewis Capaldi, Passenger (Let Her Go), Keane, Hozier (Too Sweet), Noah Kahan, LAUV, Glass Animals (Heat Waves), AURORA, BoyWithUke (Toxic). Hindi chill: The Local Train (Choo Lo, Aaoge Tum Kabhi), The Yellow Diary, Zaeden, Talwiinder (Khayaal, Dhundhala), Aditya Rikhari (Sahiba, Paro), Ritviz (Udd Gaye). Kannada chill: Raghu Dixit acoustic, Vasuki Vaibhav (Gira Gira). Tamil chill: Sid Sriram (Samajavaragamana, Parayuvaan), Hesham Abdul Wahab (Darshana, Onakka Munthiri).
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
      "songs": ["song_id_1", "song_id_2", ...]
    }
  ]
}"""


def get_spotify_client():
    return spotipy.Spotify(
        auth_manager=SpotifyOAuth(
            client_id=os.environ["SPOTIFY_CLIENT_ID"],
            client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
            redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://localhost:8888/callback"),
            scope=SCOPE,
            open_browser=True,
        )
    )


def song_summary(song):
    release = (song.get("release_date") or "")[:4] or "?"
    artists = ", ".join(song.get("artists") or [])
    album = song.get("album", "")
    name = song.get("name", "Unknown")
    return f'ID:{song["id"]} | "{name}" by {artists} | album:"{album}" | year:{release}'


def classify_with_claude(songs):
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    song_lines = "\n".join(song_summary(s) for s in songs)
    user_message = f"Classify these {len(songs)} songs into the appropriate playlists:\n\n{song_lines}"

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
                print(f"  API overloaded, retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise

    text = response.content[0].text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError("No JSON found in Claude response")
    obj, _ = json.JSONDecoder().raw_decode(text, start)
    return obj


def get_user_playlists(sp):
    user_id = sp.current_user()["id"]
    playlists = {}
    offset = 0
    while True:
        results = sp.current_user_playlists(limit=50, offset=offset)
        items = results.get("items", [])
        if not items:
            break
        for p in items:
            if p and p.get("owner", {}).get("id") == user_id:
                playlists[p["name"]] = p["id"]
        if not results.get("next"):
            break
        offset += len(items)
        time.sleep(0.1)
    return playlists


def get_playlist_existing_tracks(sp, playlist_id):
    track_ids = set()
    offset = 0
    while True:
        results = sp.playlist_items(playlist_id, fields="items(track(id)),next", limit=100, offset=offset)
        items = results.get("items", [])
        if not items:
            break
        for item in items:
            track = item.get("track")
            if track and track.get("id"):
                track_ids.add(track["id"])
        if not results.get("next"):
            break
        offset += len(items)
        time.sleep(0.1)
    return track_ids


def add_tracks_to_playlist(sp, playlist_id, track_ids):
    uris = [f"spotify:track:{tid}" for tid in track_ids]
    for i in range(0, len(uris), ADD_BATCH_SIZE):
        batch = uris[i:i + ADD_BATCH_SIZE]
        sp.playlist_add_items(playlist_id, batch)
        time.sleep(0.1)


def main():
    with open("liked_songs.json", encoding="utf-8") as f:
        all_songs = json.load(f)
    songs_by_id = {s["id"]: s for s in all_songs}

    new_songs = [songs_by_id[sid] for sid in NEW_SONG_IDS if sid in songs_by_id]
    print(f"Songs to classify and add: {len(new_songs)}")
    for s in new_songs:
        artists = ", ".join(s["artists"])
        print(f"  - {s['name']} — {artists}")

    print("\nClassifying with Claude...")
    classification = classify_with_claude(new_songs)

    assignments = {}
    for playlist in classification.get("playlists", []):
        name = playlist["name"]
        valid_ids = [sid for sid in playlist.get("songs", []) if sid in songs_by_id]
        if valid_ids:
            assignments[name] = valid_ids

    print("\nClassification result:")
    for name, ids in sorted(assignments.items()):
        songs_str = ", ".join(f'"{songs_by_id[sid]["name"]}"' for sid in ids)
        print(f"  {name}: {songs_str}")

    sp = get_spotify_client()
    user_id = sp.current_user()["id"]
    print(f"\nLogged in as: {user_id}")

    print("\nFetching your Spotify playlists...")
    user_playlists = get_user_playlists(sp)

    missing = [name for name in assignments if name not in user_playlists]
    if missing:
        print(f"\nWARNING: Playlists not found in Spotify (will be skipped):")
        for name in missing:
            print(f"  - {name}")

    print(f"\nWill add songs to these playlists:")
    for name, ids in sorted(assignments.items()):
        if name in user_playlists:
            print(f"  [{len(ids):2d} song(s)]  {name}")

    confirm = input("\nType 'yes' to proceed: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        sys.exit(0)

    added_count = 0
    skipped_count = 0
    for name, song_ids in assignments.items():
        if name not in user_playlists:
            continue
        playlist_id = user_playlists[name]
        existing_tracks = get_playlist_existing_tracks(sp, playlist_id)
        to_add = [sid for sid in song_ids if sid not in existing_tracks]
        skipped = [sid for sid in song_ids if sid in existing_tracks]
        skipped_count += len(skipped)
        if to_add:
            print(f"  Adding {len(to_add)} song(s) to '{name}'...")
            add_tracks_to_playlist(sp, playlist_id, to_add)
            added_count += len(to_add)

    print(f"\nDone!")
    print(f"  Added {added_count} track placement(s) across playlists")
    if skipped_count:
        print(f"  Skipped {skipped_count} (already in playlist)")


if __name__ == "__main__":
    main()
