from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from ai_stack.huggingface.cache import CachedRepoSnapshot
from ai_stack.huggingface.client import RepoFile, RepoSnapshot
from ai_stack.stack.manager import SetupManager


def _snapshot(repo_id: str, sha: Optional[str]) -> RepoSnapshot:
    return RepoSnapshot(
        repo_id=repo_id,
        revision="main",
        sha=sha,
        last_modified=None,
        pipeline_tag=None,
        tags=[],
        library_name=None,
        files=[RepoFile(path="model.Q4_K_M.gguf", size=1024)],
    )


@dataclass
class _FakeHF:
    snapshot_by_repo: Dict[str, RepoSnapshot]
    sha_by_repo: Dict[str, Optional[str]]
    raise_on_sha: bool = False
    sha_failures_before_success: int = 0
    snapshot_failures_before_success: int = 0
    get_snapshot_calls: int = 0
    get_sha_calls: int = 0

    def get_snapshot(self, repo_id: str, revision: str = "main") -> RepoSnapshot:
        self.get_snapshot_calls += 1
        if self.snapshot_failures_before_success > 0:
            self.snapshot_failures_before_success -= 1
            raise RuntimeError("transient snapshot failure")
        return self.snapshot_by_repo[repo_id]

    def get_repo_sha(self, repo_id: str, revision: str = "main") -> Optional[str]:
        self.get_sha_calls += 1
        if self.raise_on_sha:
            raise RuntimeError("sha lookup failed")
        if self.sha_failures_before_success > 0:
            self.sha_failures_before_success -= 1
            raise RuntimeError("transient sha failure")
        return self.sha_by_repo.get(repo_id)


@dataclass
class _FakeCache:
    cached: Optional[CachedRepoSnapshot] = None
    puts: int = 0
    touches: int = 0

    def get(self, repo_id: str, revision: str = "main") -> Optional[CachedRepoSnapshot]:
        return self.cached

    def put(self, snapshot: RepoSnapshot, last_checked: Optional[str] = None) -> None:
        self.puts += 1
        self.cached = CachedRepoSnapshot(
            key=f"{snapshot.repo_id}@{snapshot.revision}",
            sha=snapshot.sha,
            last_checked=last_checked or "now",
            snapshot=snapshot,
        )

    def touch(self, repo_id: str, revision: str = "main", last_checked: Optional[str] = None) -> None:
        self.touches += 1


def _make_manager(hf: _FakeHF, cache: _FakeCache) -> SetupManager:
    manager = object.__new__(SetupManager)
    manager.hf = hf
    manager.hf_cache = cache
    manager.hf_cache_diagnostics = {"miss": 0, "hit": 0, "refresh": 0, "fallback": 0}
    return manager


def test_snapshot_cache_miss_fetches_and_stores() -> None:
    repo_id = "org/model"
    hf = _FakeHF(snapshot_by_repo={repo_id: _snapshot(repo_id, "abc")}, sha_by_repo={repo_id: "abc"})
    cache = _FakeCache(cached=None)
    manager = _make_manager(hf, cache)

    out = manager._get_hf_snapshot(repo_id=repo_id, revision="main")

    assert out.sha == "abc"
    assert hf.get_snapshot_calls == 1
    assert hf.get_sha_calls == 0
    assert cache.puts == 1
    assert cache.touches == 0
    assert manager.get_cache_diagnostics() == {"miss": 1, "hit": 0, "refresh": 0, "fallback": 0}


def test_snapshot_cache_hit_uses_cached_when_sha_unchanged() -> None:
    repo_id = "org/model"
    cached_snapshot = _snapshot(repo_id, "abc")
    hf = _FakeHF(snapshot_by_repo={repo_id: _snapshot(repo_id, "new")}, sha_by_repo={repo_id: "abc"})
    cache = _FakeCache(
        cached=CachedRepoSnapshot(
            key=f"{repo_id}@main",
            sha="abc",
            last_checked="before",
            snapshot=cached_snapshot,
        )
    )
    manager = _make_manager(hf, cache)

    out = manager._get_hf_snapshot(repo_id=repo_id, revision="main")

    assert out.sha == "abc"
    assert hf.get_snapshot_calls == 0
    assert hf.get_sha_calls == 1
    assert cache.puts == 0
    assert cache.touches == 1
    assert manager.get_cache_diagnostics() == {"miss": 0, "hit": 1, "refresh": 0, "fallback": 0}


def test_snapshot_cache_hit_refreshes_when_sha_changes() -> None:
    repo_id = "org/model"
    cached_snapshot = _snapshot(repo_id, "old")
    fresh_snapshot = _snapshot(repo_id, "new")
    hf = _FakeHF(snapshot_by_repo={repo_id: fresh_snapshot}, sha_by_repo={repo_id: "new"})
    cache = _FakeCache(
        cached=CachedRepoSnapshot(
            key=f"{repo_id}@main",
            sha="old",
            last_checked="before",
            snapshot=cached_snapshot,
        )
    )
    manager = _make_manager(hf, cache)

    out = manager._get_hf_snapshot(repo_id=repo_id, revision="main")

    assert out.sha == "new"
    assert hf.get_snapshot_calls == 1
    assert hf.get_sha_calls == 1
    assert cache.puts == 1
    assert cache.touches == 0
    assert manager.get_cache_diagnostics() == {"miss": 0, "hit": 0, "refresh": 1, "fallback": 0}


def test_snapshot_cache_hit_falls_back_to_cached_when_sha_lookup_fails() -> None:
    repo_id = "org/model"
    cached_snapshot = _snapshot(repo_id, "old")
    hf = _FakeHF(
        snapshot_by_repo={repo_id: _snapshot(repo_id, "new")},
        sha_by_repo={repo_id: "new"},
        raise_on_sha=True,
    )
    cache = _FakeCache(
        cached=CachedRepoSnapshot(
            key=f"{repo_id}@main",
            sha="old",
            last_checked="before",
            snapshot=cached_snapshot,
        )
    )
    manager = _make_manager(hf, cache)

    out = manager._get_hf_snapshot(repo_id=repo_id, revision="main")

    assert out.sha == "old"
    assert hf.get_snapshot_calls == 0
    assert hf.get_sha_calls == 3
    assert cache.puts == 0
    assert cache.touches == 1
    assert manager.get_cache_diagnostics() == {"miss": 0, "hit": 0, "refresh": 0, "fallback": 1}


def test_snapshot_cache_hit_retries_sha_lookup_before_success() -> None:
    repo_id = "org/model"
    cached_snapshot = _snapshot(repo_id, "abc")
    hf = _FakeHF(
        snapshot_by_repo={repo_id: _snapshot(repo_id, "new")},
        sha_by_repo={repo_id: "abc"},
        sha_failures_before_success=2,
    )
    cache = _FakeCache(
        cached=CachedRepoSnapshot(
            key=f"{repo_id}@main",
            sha="abc",
            last_checked="before",
            snapshot=cached_snapshot,
        )
    )
    manager = _make_manager(hf, cache)

    out = manager._get_hf_snapshot(repo_id=repo_id, revision="main")

    assert out.sha == "abc"
    assert hf.get_sha_calls == 3
    assert cache.touches == 1
    assert manager.get_cache_diagnostics() == {"miss": 0, "hit": 1, "refresh": 0, "fallback": 0}


def test_snapshot_cache_miss_retries_snapshot_before_success() -> None:
    repo_id = "org/model"
    hf = _FakeHF(
        snapshot_by_repo={repo_id: _snapshot(repo_id, "abc")},
        sha_by_repo={repo_id: "abc"},
        snapshot_failures_before_success=2,
    )
    cache = _FakeCache(cached=None)
    manager = _make_manager(hf, cache)

    out = manager._get_hf_snapshot(repo_id=repo_id, revision="main")

    assert out.sha == "abc"
    assert hf.get_snapshot_calls == 3
    assert cache.puts == 1
    assert manager.get_cache_diagnostics() == {"miss": 1, "hit": 0, "refresh": 0, "fallback": 0}
