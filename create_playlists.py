"""
Reads playlist_plan.json and creates the playlists in your Spotify account.
Run this AFTER reviewing playlist_plan.md and being happy with the plan.
"""

import json
import os
import sys
import time
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from tqdm import tqdm

load_dotenv()

SCOPE = "user-library-read playlist-modify-public playlist-modify-private"
PLAN_FILE = "playlist_plan.json"
ADD_BATCH_SIZE = 100


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


def load_plan():
    if not os.path.exists(PLAN_FILE):
        print(f"ERROR: {PLAN_FILE} not found. Run categorize_songs.py first.")
        sys.exit(1)
    with open(PLAN_FILE, encoding="utf-8") as f:
        return json.load(f)


def create_playlist_and_add_songs(sp, user_id, playlist_data):
    name = playlist_data["name"]
    description = playlist_data.get("description", "")
    song_ids = playlist_data["songs"]

    pl = sp._post(
        "me/playlists",
        payload={"name": name, "public": False, "description": description},
    )
    pl_id = pl["id"]

    track_uris = [f"spotify:track:{sid}" for sid in song_ids]
    for i in range(0, len(track_uris), ADD_BATCH_SIZE):
        batch = track_uris[i : i + ADD_BATCH_SIZE]
        sp.playlist_add_items(pl_id, batch)
        time.sleep(0.1)

    return pl["external_urls"]["spotify"]


def main():
    plan = load_plan()
    playlists = plan.get("playlists", [])
    print(f"Plan loaded: {len(playlists)} playlists, "
          f"{sum(len(p['songs']) for p in playlists)} total songs")

    print("\nThis will CREATE the following playlists in your Spotify account (as private):")
    for p in sorted(playlists, key=lambda x: -len(x["songs"])):
        print(f"  [{len(p['songs']):3d} songs]  {p['name']}")

    print(f"\n{len(playlists)} playlists will be created.")
    confirm = input("Type 'yes' to proceed: ").strip().lower()
    if confirm != "yes":
        print("Aborted.")
        sys.exit(0)

    sp = get_spotify_client()
    user_id = sp.current_user()["id"]
    print(f"Logged in as: {user_id}")

    results = []
    for p in tqdm(playlists, desc="Creating playlists"):
        try:
            url = create_playlist_and_add_songs(sp, user_id, p)
            results.append({"name": p["name"], "songs": len(p["songs"]), "url": url})
        except Exception as e:
            print(f"\nERROR creating '{p['name']}': {e}")
            results.append({"name": p["name"], "songs": len(p["songs"]), "url": None, "error": str(e)})

    print("\n=== Created Playlists ===")
    for r in results:
        status = r["url"] or f"FAILED: {r.get('error')}"
        print(f"  {r['name']} ({r['songs']} songs) — {status}")


if __name__ == "__main__":
    main()
