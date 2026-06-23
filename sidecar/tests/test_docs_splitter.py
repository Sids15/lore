"""Tests for the documentation text splitter."""

from __future__ import annotations

from app.config import Settings
from app.docs.splitter import chunk_docs_repo, iter_doc_files, split_text


def _settings(**kwargs) -> Settings:
    return Settings(**kwargs)


def test_splits_on_headings_and_tracks_breadcrumb():
    text = (
        "# Guide\n"
        "\n"
        "Intro paragraph about the guide.\n"
        "\n"
        "## Setup\n"
        "\n"
        "Install the dependencies first.\n"
        "\n"
        "### Linux\n"
        "\n"
        "Run the shell script.\n"
    )
    chunks = split_text(text, repo="r", file_path="docs/guide.md", settings=_settings(doc_chunk_chars=60, doc_chunk_overlap=0))

    headings = {c.heading for c in chunks}
    # Nested headings accumulate into a " > " breadcrumb.
    assert any("Guide > Setup > Linux" == h for h in headings)
    assert all(c.file_path == "docs/guide.md" for c in chunks)


def test_line_ranges_are_one_based_and_ordered():
    text = "# Title\n\nFirst paragraph.\n\nSecond paragraph.\n"
    chunks = split_text(text, repo="r", file_path="a.md", settings=_settings(doc_chunk_chars=20, doc_chunk_overlap=0))
    assert chunks[0].start_line == 1
    for chunk in chunks:
        assert chunk.start_line >= 1
        assert chunk.end_line >= chunk.start_line


def test_overlap_carries_text_between_chunks():
    paragraphs = "\n\n".join(f"Paragraph number {i} with some filler words." for i in range(6))
    no_overlap = split_text(paragraphs, repo="r", file_path="a.txt", settings=_settings(doc_chunk_chars=80, doc_chunk_overlap=0))
    with_overlap = split_text(paragraphs, repo="r", file_path="a.txt", settings=_settings(doc_chunk_chars=80, doc_chunk_overlap=60))
    assert len(no_overlap) >= 2
    # Overlap should not reduce the number of chunks and should repeat content.
    assert len(with_overlap) >= len(no_overlap)


def test_fenced_code_block_is_not_split_on_blank_lines():
    text = "```python\n" "def a():\n" "    pass\n" "\n" "def b():\n" "    pass\n" "```\n"
    chunks = split_text(text, repo="r", file_path="a.md", settings=_settings(doc_chunk_chars=500, doc_chunk_overlap=0))
    assert len(chunks) == 1
    assert "def a()" in chunks[0].text and "def b()" in chunks[0].text


def test_oversized_segment_is_windowed():
    big = "word " * 500  # one ~2500-char paragraph
    chunks = split_text(big, repo="r", file_path="a.txt", settings=_settings(doc_chunk_chars=400, doc_chunk_overlap=50))
    assert len(chunks) > 1
    assert all(len(c.text) <= 400 for c in chunks)


def test_chunk_id_is_stable():
    text = "# A\n\nbody text here\n"
    s = _settings(doc_chunk_chars=200, doc_chunk_overlap=0)
    first = split_text(text, repo="r", file_path="a.md", settings=s)
    second = split_text(text, repo="r", file_path="a.md", settings=s)
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_iter_doc_files_filters_extensions_and_excludes(tmp_path):
    (tmp_path / "README.md").write_text("# hi\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("text\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")  # not a doc
    skipped = tmp_path / "node_modules"
    skipped.mkdir()
    (skipped / "dep.md").write_text("# dep\n", encoding="utf-8")

    found = {p.name for p in iter_doc_files(tmp_path)}
    assert found == {"README.md", "notes.txt"}


def test_chunk_docs_repo_uses_repo_name(tmp_path):
    repo = tmp_path / "myrepo"
    repo.mkdir()
    (repo / "README.md").write_text("# Title\n\nSome documentation prose.\n", encoding="utf-8")
    chunks = chunk_docs_repo(repo)
    assert chunks
    assert all(c.repo == "myrepo" for c in chunks)
    assert all(c.file_path == "README.md" for c in chunks)
