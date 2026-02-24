from __future__ import annotations

import json

from ai_stack.huggingface.cache import HuggingFaceSnapshotCache


def test_cache_schema_mismatch_recreates_store(tmp_path) -> None:
    cache_path = tmp_path / "huggingface" / "cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 999,
                "updated_at": "2020-01-01T00:00:00+00:00",
                "repos": {
                    "org/model@main": {
                        "sha": "deadbeef",
                        "last_checked": "2020-01-01T00:00:00+00:00",
                        "snapshot": {"repo_id": "org/model", "revision": "main", "files": []},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    cache = HuggingFaceSnapshotCache(cache_path=cache_path)
    data = cache.ensure_cache()

    assert data["schema_version"] == HuggingFaceSnapshotCache.SCHEMA_VERSION
    assert data["repos"] == {}
