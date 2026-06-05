"""
Fetches all liked songs from Spotify with full metadata and saves to JSON.
Run this first before categorize_songs.py.
"""

import json
import os
import time
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from tqdm import tqdm

load_dotenv()

SCOPE = "user-library-read"
CACHE_FILE = "liked_songs.json"
AUDIO_FEATURES_BATCH = 100
ARTIST_BATCH = 50


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


def fetch_all_liked_songs(sp):
    songs = []
    offset = 0
    limit = 50
    print("Fetching liked songs...")
    while True:
        results = sp.current_user_saved_tracks(limit=limit, offset=offset)
        items = results.get("items", [])
        if not items:
            break
        songs.extend(items)
        offset += len(items)
        print(f"  Fetched {len(songs)} songs so far...", end="\r")
        if not results.get("next"):
            break
        time.sleep(0.1)
    print(f"\nTotal liked songs: {len(songs)}")
    return songs


def fetch_audio_features(sp, track_ids):
    features = {}
    for i in range(0, len(track_ids), AUDIO_FEATURES_BATCH):
        batch = track_ids[i : i + AUDIO_FEATURES_BATCH]
        try:
            results = sp.audio_features(batch)
            for f in results:
                if f:
                    features[f["id"]] = f
        except Exception:
            pass  # audio-features endpoint deprecated for dev-mode apps
        time.sleep(0.1)
    return features


def fetch_artist_genres(sp, artist_ids):
    genres = {}
    unique_ids = list(set(artist_ids))
    for i in tqdm(range(0, len(unique_ids), ARTIST_BATCH), desc="Fetching artist genres"):
        batch = unique_ids[i : i + ARTIST_BATCH]
        try:
            results = sp.artists(batch)
            for artist in results.get("artists", []):
                if artist:
                    genres[artist["id"]] = artist.get("genres", [])
        except Exception:
            pass  # artists batch endpoint restricted for dev-mode apps
        time.sleep(0.1)
    return genres


def build_song_records(saved_tracks, audio_features, artist_genres):
    records = []
    for item in saved_tracks:
        track = item["track"]
        if not track:
            continue
        tid = track["id"]
        af = audio_features.get(tid, {})
        all_genres = []
        for artist in track.get("artists", []):
            all_genres.extend(artist_genres.get(artist["id"], []))
        # deduplicate genres while preserving order
        seen = set()
        unique_genres = []
        for g in all_genres:
            if g not in seen:
                seen.add(g)
                unique_genres.append(g)

        records.append(
            {
                "id": tid,
                "name": track["name"],
                "artists": [a["name"] for a in track.get("artists", [])],
                "album": track.get("album", {}).get("name", ""),
                "release_date": track.get("album", {}).get("release_date", ""),
                "popularity": track.get("popularity", 0),
                "explicit": track.get("explicit", False),
                "added_at": item.get("added_at", ""),
                "genres": unique_genres,
                "audio_features": {
                    "danceability": af.get("danceability"),
                    "energy": af.get("energy"),
                    "valence": af.get("valence"),
                    "tempo": af.get("tempo"),
                    "acousticness": af.get("acousticness"),
                    "instrumentalness": af.get("instrumentalness"),
                    "speechiness": af.get("speechiness"),
                    "loudness": af.get("loudness"),
                    "key": af.get("key"),
                    "mode": af.get("mode"),
                    "time_signature": af.get("time_signature"),
                },
                "duration_ms": track.get("duration_ms", 0),
                "preview_url": track.get("preview_url"),
                "spotify_url": track.get("external_urls", {}).get("spotify", ""),
            }
        )
    return records


def main():
    sp = get_spotify_client()

    saved_tracks = fetch_all_liked_songs(sp)
    track_ids = [item["track"]["id"] for item in saved_tracks if item.get("track")]
    artist_ids = [
        artist["id"]
        for item in saved_tracks
        if item.get("track")
        for artist in item["track"].get("artists", [])
    ]

    print("Fetching audio features...")
    audio_features = fetch_audio_features(sp, track_ids)

    artist_genres = fetch_artist_genres(sp, artist_ids)

    records = build_song_records(saved_tracks, audio_features, artist_genres)

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    print(f"\nSaved {len(records)} songs to {CACHE_FILE}")
    print("Next: run  python categorize_songs.py")


if __name__ == "__main__":
    main()
