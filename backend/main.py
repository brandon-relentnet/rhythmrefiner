#!/usr/bin/env python3
import base64
import os
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Set, Tuple, Optional

import re
import requests
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

TOKEN_URL = "https://accounts.spotify.com/api/token"
TRACKS_BASE_URL = "https://api.spotify.com/v1/playlists/{playlist_id}/tracks"

app = FastAPI()

ALLOW_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "https://rhythmrefiner.com",
    "https://www.rhythmrefiner.com",
    "https://api.rhythmrefiner.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Request models ----------


class PlaylistRequest(BaseModel):
    playlistUrl: str


class RecommendationsRequest(BaseModel):
    playlistUrl: str
    maxArtistCount: Optional[int] = None


# ---------- API endpoints ----------


@app.post("/api/playlist-summary")
def playlist_summary(req: PlaylistRequest) -> Dict[str, Any]:
    """
    Returns basic info about a playlist:
      - totalTracks
      - uniqueArtists
      - artists[] with {name, url, count, share, tracks[]}
    """
    try:
        playlist_id = extract_playlist_id(req.playlistUrl)
        client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        token = get_access_token(client_id, client_secret)
        artists, total_tracks, _track_ids, _signatures = fetch_artist_data_fast(
            playlist_id, token, max_workers=8
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    artist_list = []
    for a in artists.values():
        share = (a["count"] / total_tracks * 100) if total_tracks > 0 else 0.0  # type: ignore
        artist_list.append(
            {
                "name": a["name"],
                "url": a["url"],
                "count": a["count"],
                "share": share,
                "tracks": a["tracks"],
            }
        )

    artist_list.sort(key=lambda x: (-x["count"], x["name"].lower()))

    return {
        "totalTracks": total_tracks,
        "uniqueArtists": len(artist_list),
        "artists": artist_list,
    }


@app.post("/api/recommendations")
def recommendations(req: RecommendationsRequest) -> Dict[str, Any]:
    """
    Recommendation strategy (no audio-features):

    1. Scan the playlist:
       - Count artist occurrences
       - Collect track IDs
       - Collect track signatures for duplicate detection

    2. Build a 'genre profile' of the playlist via artists' genres.

    3. Take the top N artists by occurrence.

    4. For each of those artists, fetch their top tracks:
       - Exclude tracks already in the playlist.
       - Exclude tracks considered duplicates by signature.

    5. Score each candidate using:
       - artist_score: playlist frequency of that artist
       - rank_score: position in artist's top tracks (1–10)
       - genre_score: overlap between playlist genres and artist genres
       - pop_score: track popularity
       - balance_penalty: avoid over-representing a single artist

    6. Return candidates sorted by confidencePct descending.
    """
    try:
        playlist_id = extract_playlist_id(req.playlistUrl)
        client_id = os.environ.get("SPOTIFY_CLIENT_ID", "")
        client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
        token = get_access_token(client_id, client_secret)
        artists, total_tracks, track_ids, track_signatures = fetch_artist_data_fast(
            playlist_id, token, max_workers=6
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    if not artists or not track_ids:
        raise HTTPException(
            status_code=400, detail="Playlist is empty or cannot be processed"
        )

    # Build playlist genre profile
    try:
        playlist_genre_profile, artist_genres = compute_playlist_genre_profile(
            token, list(artists.keys())
        )
    except Exception:
        # Fail soft: continue without genre signal if Spotify blocks this for some reason
        playlist_genre_profile, artist_genres = {}, {}

    # Parameters
    TOP_ARTIST_COUNT = 20
    TOP_TRACKS_PER_ARTIST = 10

    sorted_artists = sorted(
        artists.items(),
        key=lambda item: (-item[1]["count"], item[1]["name"].lower()),  # type: ignore
    )
    artist_count_filter = req.maxArtistCount
    if artist_count_filter is not None:
        eligible_artists = [
            item for item in sorted_artists if item[1]["count"] <= artist_count_filter  # type: ignore[index]
        ]
        random.shuffle(eligible_artists)
        top_artists = eligible_artists[:TOP_ARTIST_COUNT]
    else:
        top_artists = sorted_artists[:TOP_ARTIST_COUNT]

    existing_track_ids = set(track_ids)
    candidate_tracks: Dict[str, Dict[str, Any]] = {}

    # Collect candidate tracks
    top_tracks_by_artist = fetch_top_tracks_for_artists(
        [aid for aid, _ in top_artists], access_token=token, market="US", max_workers=8
    )
    for artist_id, meta in top_artists:
        top_tracks = top_tracks_by_artist.get(artist_id, [])
        if not top_tracks:
            continue

        for rank_idx, t in enumerate(top_tracks[:TOP_TRACKS_PER_ARTIST], start=1):
            tid = t.get("id")
            if not tid:
                continue
            if tid in existing_track_ids:
                continue
            if tid in candidate_tracks:
                continue

            # Skip duplicates using track signatures
            signature = make_track_signature(t.get("name", ""), t.get("artists", []))
            if signature and signature in track_signatures:
                continue

            artist_info = (t.get("artists") or [{}])[0]
            candidate_tracks[tid] = {
                "id": tid,
                "name": t.get("name", "Unknown track"),
                "url": (t.get("external_urls") or {}).get("spotify", ""),
                "artistId": artist_id,
                "artistName": artist_info.get("name", "Unknown artist"),
                "artistUrl": (artist_info.get("external_urls") or {}).get(
                    "spotify", ""
                ),
                "trackRank": rank_idx,
                "popularity": int(t.get("popularity", 0)),
                "rawSpotify": t,
            }

    if not candidate_tracks:
        return {
            "totalTracks": total_tracks,
            "recommendedTracks": [],
            "playlistGenreProfile": playlist_genre_profile,
            "info": "No candidate tracks found (all top tracks are already in the playlist?).",
        }

    max_artist_count = max(a["count"] for a in artists.values()) if artists else 1

    scored_tracks = []
    for tid, cand in candidate_tracks.items():
        artist_id = cand["artistId"]
        artist_data = artists.get(artist_id, {})
        artist_count = int(artist_data.get("count", 0))

        track_rank = int(cand["trackRank"])
        popularity = int(cand.get("popularity", 0))

        genre_score = compute_genre_score(
            artist_id=artist_id,
            playlist_genre_profile=playlist_genre_profile,
            artist_genres=artist_genres,
        )

        score_components = score_candidate_track(
            artist_count=artist_count,
            max_artist_count=max_artist_count,
            track_rank=track_rank,
            track_popularity=popularity,
            playlist_length=total_tracks,
            genre_score=genre_score,
        )

        scored_tracks.append(
            {
                "id": cand["id"],
                "name": cand["name"],
                "url": cand["url"],
                "artistId": cand["artistId"],
                "artistName": cand["artistName"],
                "artistUrl": cand["artistUrl"],
                "trackRank": track_rank,
                "popularity": popularity,
                "scores": score_components,
                "confidencePct": score_components["confidencePct"],
            }
        )

    # Sort and trim
    scored_tracks.sort(
        key=lambda t: (
            -t["confidencePct"],
            t["artistName"].lower(),
            t["name"].lower(),
        )
    )
    TOP_RETURNED = 100
    scored_tracks = scored_tracks[:TOP_RETURNED]

    return {
        "totalTracks": total_tracks,
        "recommendedTracks": scored_tracks,
        "playlistGenreProfile": playlist_genre_profile,
        "weights": {
            "artist": 0.4,
            "rank": 0.25,
            "genre": 0.15,
            "popularity": 0.2,
            "targetArtistShare": 0.15,
        },
    }


# ---------- Core helpers ----------


def extract_playlist_id(raw: str) -> str:
    raw = raw.strip()

    m = re.search(r"open\.spotify\.com/playlist/([a-zA-Z0-9]+)", raw)
    if m:
        return m.group(1)

    if raw.startswith("spotify:playlist:"):
        return raw.split(":")[-1]

    return raw


def get_access_token(client_id: str, client_secret: str) -> str:
    if not client_id or not client_secret:
        raise RuntimeError(
            "You must set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET environment variables."
        )

    auth_bytes = f"{client_id}:{client_secret}".encode("utf-8")
    auth_header = base64.b64encode(auth_bytes).decode("utf-8")

    headers = {
        "Authorization": f"Basic {auth_header}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}

    resp = requests.post(TOKEN_URL, headers=headers, data=data, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get access token: {resp.status_code} {resp.text}")

    return resp.json()["access_token"]


def fetch_page(
    playlist_id: str,
    access_token: str,
    offset: int,
    limit: int = 100,
    include_total: bool = False,
):
    """
    Fetch a single page of tracks from a playlist.
    """
    url = TRACKS_BASE_URL.format(playlist_id=playlist_id)

    if include_total:
        fields = (
            "items(track(id,name,external_urls,artists(id,name,external_urls),is_local)),total"
        )
    else:
        fields = "items(track(id,name,external_urls,artists(id,name,external_urls),is_local))"

    params = {
        "limit": limit,
        "offset": offset,
        "fields": fields,
    }
    headers = {"Authorization": f"Bearer {access_token}"}

    resp = requests.get(url, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch tracks (offset {offset}): {resp.status_code} {resp.text}"
        )

    return resp.json()


def fetch_artist_data_fast(
    playlist_id: str,
    access_token: str,
    max_workers: int = 8,
):
    """
    Returns:
      artists: {
        artist_id: {
          "name": str,
          "url": str,
          "count": int,
          "tracks": [
             { "name": str, "url": str, "order": int, "id": str }
          ]
        }
      }
      total_tracks: int (non-local)
      track_ids: [str] (playlist order)
      track_signatures: set of normalized (track, artist) signatures
    """
    limit = 100

    first_page = fetch_page(
        playlist_id=playlist_id,
        access_token=access_token,
        offset=0,
        limit=limit,
        include_total=True,
    )

    total = first_page.get("total", 0)
    items = list(first_page.get("items", []))

    if total <= limit:
        all_items = items
    else:
        offsets = list(range(limit, total, limit))
        all_items = items

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_offset = {
                executor.submit(
                    fetch_page,
                    playlist_id,
                    access_token,
                    offset,
                    limit,
                    False,
                ): offset
                for offset in offsets
            }

            for future in as_completed(future_to_offset):
                offset = future_to_offset[future]
                try:
                    page_data = future.result()
                    all_items.extend(page_data.get("items", []))
                except Exception as e:
                    raise RuntimeError(f"Error fetching offset {offset}: {e}")

    artist_counts: Counter[str] = Counter()
    artist_meta: Dict[str, Dict[str, str]] = {}
    artist_tracks: Dict[str, List[Dict[str, Any]]] = {}
    total_tracks = 0
    order_counter = 0
    track_ids: List[str] = []
    track_signatures: Set[str] = set()

    for item in all_items:
        track = item.get("track")
        if not track:
            continue
        if track.get("is_local"):
            continue

        total_tracks += 1
        order_counter += 1

        track_name = track.get("name") or "Unknown track"
        track_urls = track.get("external_urls") or {}
        track_id = track.get("id", "")
        track_url = track_urls.get("spotify", "")

        if track_id:
            track_ids.append(track_id)

        signature = make_track_signature(track_name, track.get("artists", []))
        if signature:
            track_signatures.add(signature)

        for artist in track.get("artists", []):
            artist_id = artist.get("id")
            name = artist.get("name")
            external_urls = artist.get("external_urls") or {}
            url = external_urls.get("spotify", "")

            if not artist_id or not name:
                continue

            artist_counts[artist_id] += 1

            if artist_id not in artist_meta:
                artist_meta[artist_id] = {
                    "name": name,
                    "url": url,
                }

            artist_tracks.setdefault(artist_id, []).append(
                {
                    "name": track_name,
                    "url": track_url,
                    "order": order_counter,
                    "id": track_id,
                }
            )

    artists: Dict[str, Dict[str, Any]] = {}
    for artist_id, count in artist_counts.items():
        meta = artist_meta.get(artist_id, {})
        tracks = artist_tracks.get(artist_id, [])
        tracks_sorted = sorted(tracks, key=lambda t: t["order"])

        artists[artist_id] = {
            "name": meta.get("name", "Unknown"),
            "url": meta.get("url", ""),
            "count": count,
            "tracks": tracks_sorted,
        }

    return artists, total_tracks, track_ids, track_signatures


def fetch_artist_top_tracks(
    artist_id: str,
    access_token: str,
    market: str = "US",
):
    url = f"https://api.spotify.com/v1/artists/{artist_id}/top-tracks"
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"market": market}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    if resp.status_code != 200:
        return []
    return resp.json().get("tracks", [])


def fetch_top_tracks_for_artists(
    artist_ids: List[str],
    access_token: str,
    market: str = "US",
    max_workers: int = 8,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch top tracks for many artists in parallel to reduce total latency.
    """
    if not artist_ids:
        return {}

    results: Dict[str, List[Dict[str, Any]]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_artist_top_tracks, aid, access_token, market): aid
            for aid in artist_ids
        }
        for future in as_completed(future_map):
            aid = future_map[future]
            try:
                tracks = future.result()
            except Exception:
                continue
            if tracks:
                results[aid] = tracks
    return results


def chunked(iterable, size: int):
    """Yield lists of length <= size from iterable."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


# ---------- Duplicate-detection helpers ----------


def normalize_track_title(title: str) -> str:
    title = title.lower().strip()
    title = re.sub(r"\s*\(.*?\)", "", title)
    title = re.sub(r"\s*\[.*?\]", "", title)
    title = re.sub(
        r"\s+-\s*(remaster(ed)?\s*\d*|live.*|radio edit.*)",
        "",
        title,
    )
    title = re.sub(r"\s+", " ", title)
    return title.strip()


def make_track_signature(title: str, artists: List[Dict[str, Any]]) -> str:
    if not title or not artists:
        return ""
    primary_artist = artists[0].get("name", "").lower().strip()
    norm_title = normalize_track_title(title)
    if not primary_artist or not norm_title:
        return ""
    return f"{norm_title}|{primary_artist}"


# ---------- Genre-based helpers ----------


def fetch_artists_genres(
    access_token: str,
    artist_ids: List[str],
) -> Dict[str, List[str]]:
    """
    Batch-fetch artists and return {artist_id: [genres...]}.
    Uses /v1/artists?ids=... (max 50 per request).
    """
    if not artist_ids:
        return {}

    headers = {"Authorization": f"Bearer {access_token}"}
    genres_by_id: Dict[str, List[str]] = {}

    for batch in chunked(artist_ids, 50):
        url = "https://api.spotify.com/v1/artists"
        params = {"ids": ",".join(batch)}
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(
                f"fetch_artists_genres failed: {resp.status_code} {resp.text}"
            )
        data = resp.json()
        for artist in data.get("artists", []):
            if not artist:
                continue
            aid = artist.get("id")
            if not aid:
                continue
            genres = artist.get("genres") or []
            genres_by_id[aid] = [g.lower() for g in genres]

    return genres_by_id


def compute_playlist_genre_profile(
    access_token: str,
    artist_ids: List[str],
) -> Tuple[Dict[str, float], Dict[str, List[str]]]:
    """
    Build a genre profile for the playlist.

    Returns:
      (playlist_genre_weights, artist_genres)

      playlist_genre_weights: {genre: weight in (0,1]}
      artist_genres: {artist_id: [genres...]}
    """
    artist_genres = fetch_artists_genres(access_token, artist_ids)
    counter: Counter[str] = Counter()

    for genres in artist_genres.values():
        for g in genres:
            counter[g] += 1

    total = sum(counter.values())
    if total == 0:
        return {}, artist_genres

    weights = {g: c / total for g, c in counter.items()}
    return weights, artist_genres


def compute_genre_score(
    artist_id: str,
    playlist_genre_profile: Dict[str, float],
    artist_genres: Dict[str, List[str]],
) -> float:
    """
    Returns a genre similarity in [0,1].

    1. Take the playlist's top N genres by weight.
    2. Take the candidate artist's genres.
    3. Compute Jaccard similarity: |intersection| / |union|.

    If we have no info, return a neutral-ish value.
    """
    if not playlist_genre_profile:
        return 0.5

    genres = artist_genres.get(artist_id, [])
    if not genres:
        return 0.4

    candidate_set = set(genres)

    TOP_GENRES = 15
    top_playlist_genres = sorted(
        playlist_genre_profile.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:TOP_GENRES]
    playlist_set = {g for g, _ in top_playlist_genres}

    if not playlist_set:
        return 0.5

    intersection = candidate_set & playlist_set
    union = candidate_set | playlist_set
    if not union:
        return 0.5

    return len(intersection) / len(union)


# ---------- Scoring ----------


def score_candidate_track(
    *,
    artist_count: int,
    max_artist_count: int,
    track_rank: int,
    track_popularity: int,
    playlist_length: int,
    genre_score: float,
    target_artist_share: float = 0.15,
) -> Dict[str, float]:
    """
    Compute all the component scores and the final confidence.
    """

    if max_artist_count <= 0:
        max_artist_count = 1
    if playlist_length <= 0:
        playlist_length = 1
    if track_rank < 1:
        track_rank = 1
    if track_rank > 10:
        track_rank = 10

    artist_score = artist_count / max_artist_count
    rank_score = (11 - track_rank) / 10.0
    pop_score = max(0.0, min(1.0, track_popularity / 100.0))
    genre_score = max(0.0, min(1.0, genre_score))

    artist_share = artist_count / playlist_length
    if artist_share <= target_artist_share:
        balance_penalty = 1.0
    else:
        balance_penalty = max(0.05, target_artist_share / artist_share)

    # Weights (tweakable)
    w_artist = 0.4
    w_rank = 0.25
    w_pop = 0.2
    w_genre = 0.15

    raw_score = (
        w_artist * artist_score
        + w_rank * rank_score
        + w_pop * pop_score
        + w_genre * genre_score
    )

    final_score = raw_score * balance_penalty
    final_score = max(0.0, min(1.0, final_score))

    return {
        "artistCount": artist_count,
        "artistShare": artist_share,
        "artistScore": artist_score,
        "rankScore": rank_score,
        "genreScore": genre_score,
        "popularityScore": pop_score,
        "balancePenalty": balance_penalty,
        "rawScore": raw_score,
        "finalScore": final_score,
        "confidencePct": round(final_score * 100, 1),
    }
