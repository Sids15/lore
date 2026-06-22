"""Walk a repository's commit log with gitpython."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import git
from git import NULL_TREE, Repo

# Per-commit raw diff is truncated — it is for display/summary context only.
_MAX_DIFF_CHARS = 4000


@dataclass
class WalkedCommit:
    """One commit's extracted data."""

    sha: str
    author: str
    author_email: str
    committed_at: str  # ISO-8601
    message: str
    files: list[tuple[str, str]] = field(default_factory=list)  # (path, change_type)
    diff: str = ""  # truncated unified diff (not embedded)


def open_repo(repo_path: Path) -> Repo | None:
    """Open a git repo, or return None if the path isn't one."""
    try:
        return Repo(repo_path)
    except (git.InvalidGitRepositoryError, git.NoSuchPathError):
        return None


def _changed_files(commit, parent) -> list[tuple[str, str]]:
    try:
        diffs = commit.diff(parent) if parent is not None else commit.diff(NULL_TREE)
    except git.GitError:
        return []
    out: list[tuple[str, str]] = []
    for d in diffs:
        path = d.b_path or d.a_path
        if path:
            out.append((path, d.change_type or "M"))
    return out


def _truncated_diff(repo: Repo, sha: str) -> str:
    try:
        text = repo.git.show(sha, "--no-color", "--format=")
    except git.GitError:
        return ""
    return text[:_MAX_DIFF_CHARS]


def walk(repo_path: Path, max_commits: int) -> list[WalkedCommit] | None:
    """Return up to ``max_commits`` most-recent commits, or None if not a git repo."""
    repo = open_repo(repo_path)
    if repo is None or repo.bare:
        return None
    try:
        commits = list(repo.iter_commits("HEAD", max_count=max_commits))
    except git.GitError:
        return []  # repo with no commits yet

    walked: list[WalkedCommit] = []
    for commit in commits:
        parent = commit.parents[0] if commit.parents else None
        walked.append(
            WalkedCommit(
                sha=commit.hexsha,
                author=commit.author.name or "",
                author_email=commit.author.email or "",
                committed_at=commit.committed_datetime.isoformat(),
                message=str(commit.message).strip(),
                files=_changed_files(commit, parent),
                diff=_truncated_diff(repo, commit.hexsha),
            )
        )
    return walked
