# Spotify Playlist Organiser

Automatically organises your Spotify liked songs into smart playlists using AI. It analyses your songs by mood, genre, language, era, and vibe — then creates the playlists directly in your Spotify account.

## What it does

1. **Fetches** all your liked songs from Spotify (with audio features like energy, tempo, danceability)
2. **Categorises** them into playlists using Claude AI (e.g. "Bollywood Sad Classics", "Tamil Workout Bangers", "Late Night English Indie")
3. **Creates** those playlists in your Spotify account automatically

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/sorv2k/spotify-playlists.git
cd spotify-playlists
```

### 2. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
# .venv\Scripts\activate       # Windows

pip install -r requirements.txt
```

### 3. Get your API keys

You need two sets of credentials:

**Spotify:**
1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Create a new app
3. Set the Redirect URI to `http://127.0.0.1:8888/callback`
4. Copy your **Client ID** and **Client Secret**

**Anthropic (Claude AI):**
1. Go to [Anthropic Console](https://console.anthropic.com)
2. Create an API key

### 4. Configure your credentials

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```
SPOTIFY_CLIENT_ID=your_client_id_here
SPOTIFY_CLIENT_SECRET=your_client_secret_here
SPOTIFY_REDIRECT_URI=http://127.0.0.1:8888/callback
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

## Usage

Run the three scripts in order:

### Step 1 — Fetch your liked songs

```bash
python fetch_songs.py
```

This logs you into Spotify (opens a browser for auth), then downloads all your liked songs with audio features into `liked_songs.json`. Takes a few minutes depending on your library size.

### Step 2 — Categorise into playlists

```bash
python categorize_songs.py
```

Sends your songs to Claude AI in batches to group them into playlists. Generates:
- `playlist_plan.md` — a readable report of all proposed playlists
- `playlist_plan.json` — the machine-readable plan used in the next step

Review `playlist_plan.md` to see the proposed playlists before creating them.

### Step 3 — Create the playlists on Spotify

```bash
python create_playlists.py
```

Creates all the playlists in your Spotify account and adds the songs.

## Keeping playlists up to date

Once your playlists exist in Spotify, use this script whenever you like new songs:

```bash
python add_new_songs.py
```

It fetches any liked songs not yet in `liked_songs.json`, classifies them with Claude into your existing playlists, adds them on Spotify, and updates `liked_songs.json` with the new entries. Safe to re-run any time — it skips songs it's already seen and skips tracks already present in a target playlist.

## Utility scripts

These were written for one-off maintenance and contain hardcoded data from the sessions they were built for. Treat them as references rather than turnkey commands — edit the constants at the top of the file before running.

- **`add_missed_songs.py`** — classifies and adds a hardcoded list of song IDs that were fetched but never added to a playlist. Update `NEW_SONG_IDS` before running.
- **`merge_artist_playlists.py`** — asks Claude to fold artist-specific playlists (e.g. "The Weeknd: Starboy to After Hours") into broader genre/era playlists in `playlist_plan.json`. Update `ARTIST_PLAYLIST_NAMES` before running.

## Cost

Step 2 uses the Claude API which has a small cost. For a library of ~800 songs it costs roughly **$0.30–0.50**.

## Notes

- Your `liked_songs.json` is not committed to git — it contains your personal data
- Your `.env` file is also excluded — never share it
- You can re-run Step 2 any time to regenerate the playlist plan without re-fetching songs
