from app.spotify import episode_candidate


def test_spotify_episode_candidate_keeps_catalog_metadata_outside_ai_processing():
    candidate = episode_candidate(
        {
            "name": "Eine lange Folge",
            "description": "Ein Gespräch über Gesellschaft und Technologie.",
            "duration_ms": 3_720_000,
            "release_date": "2026-08-26",
            "external_urls": {"spotify": "https://open.spotify.com/episode/abc123"},
            "show": {"name": "Testpodcast"},
        },
        query="Technologie und Gesellschaft",
        interests=["Technologie", "Gesellschaft"],
    )

    assert candidate is not None
    assert candidate["spotify_url"] == "https://open.spotify.com/episode/abc123"
    assert candidate["duration_minutes"] == 62
    assert candidate["topics"] == ["Technologie", "Gesellschaft"]


def test_spotify_episode_candidate_rejects_non_episode_urls():
    assert episode_candidate(
        {"name": "Folge", "external_urls": {"spotify": "https://open.spotify.com/show/abc"}, "show": {"name": "Testpodcast"}},
        query="Test",
        interests=[],
    ) is None
