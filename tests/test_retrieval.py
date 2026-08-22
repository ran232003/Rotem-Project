from __future__ import annotations

import numpy as np
import pytest

from rotem_agent.matters.registry import load_matter
from rotem_agent.retrieval.embed import HashEmbedder, unit
from rotem_agent.retrieval.hebrew import index_terms, tokens, variants
from rotem_agent.retrieval.ingest import ingest_matter
from rotem_agent.retrieval.search import search
from rotem_agent.retrieval.store import ChunkStore


# ------------------------------------------------------------------ tokenising

def test_visa_classes_survive_as_single_terms():
    """ב/1 and א/5 are distinct legal statuses; splitting them conflates every visa."""
    assert "ב/1" in tokens("אשרת עבודה מסוג ב/1")
    assert "א/5" in tokens("מעמד א/5")


def test_a_visa_class_keeps_its_leading_letter():
    """The ב of ב/1 is the class, not the preposition 'in', so it must not be stripped."""
    assert variants("ב/1") == ["ב/1"]


def test_final_letters_fold_so_inflections_match():
    assert "שלומ" in variants("שלום")


def test_attached_prefix_is_indexed_alongside_the_surface_form():
    forms = variants("והמסמכים")
    assert "והמסמכים" in forms
    assert "המסמכים" in forms


def test_short_words_keep_their_prefix():
    assert variants("בית") == ["בית"]


def test_niqqud_does_not_split_a_word():
    assert tokens("שָׁלוֹם") == ["שלום"]


# ---------------------------------------------------------------------- ingest

def _matter(tmp_path, files: dict[str, str]):
    directory = tmp_path / "anna-reentry"
    (directory / "docs").mkdir(parents=True)
    (directory / "matter.yaml").write_text(
        "client_name: Anna\ncategory: reentry_visa\naddresses:\n  - anna@example.com\n",
        encoding="utf-8",
    )
    for name, content in files.items():
        target = directory / "docs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return load_matter(directory)


def test_ingest_indexes_files_and_reports_chunks(tmp_path):
    matter = _matter(tmp_path, {"letter.txt": "בקשה לאשרת חוזר עבור אנה. " * 40})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        summary = ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        assert summary.added == ["letter.txt"]
        assert summary.chunks > 0


def test_unchanged_files_are_not_reprocessed(tmp_path):
    matter = _matter(tmp_path, {"letter.txt": "מסמך " * 200})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        second = ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
    assert second.unchanged == ["letter.txt"] and not second.added


def test_editing_a_file_reindexes_it(tmp_path):
    matter = _matter(tmp_path, {"letter.txt": "גרסה ראשונה " * 50})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        (matter.docs_dir / "letter.txt").write_text("גרסה שנייה " * 50, encoding="utf-8")
        second = ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        assert second.added == ["letter.txt"]
        assert all("ראשונה" not in c.text for c in store.load_chunks(matter.slug))


def test_a_deleted_file_stops_being_retrievable(tmp_path):
    """A document withdrawn from a matter must not keep appearing in drafts."""
    matter = _matter(tmp_path, {"a.txt": "אשרת חוזר " * 50, "b.txt": "מסמך אחר " * 50})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        (matter.docs_dir / "a.txt").unlink()
        summary = ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        assert summary.removed == ["a.txt"]
        assert {c.rel_path for c in store.load_chunks(matter.slug)} == {"b.txt"}


def test_unsupported_files_are_reported_not_indexed(tmp_path):
    matter = _matter(tmp_path, {"scan.jpg": "not text"})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        summary = ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
    assert summary.skipped == ["scan.jpg"] and not summary.added


def test_nested_folders_are_indexed_with_relative_paths(tmp_path):
    matter = _matter(tmp_path, {"ministry/letter.txt": "החלטת הרשות " * 50})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        summary = ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
    assert summary.added == ["ministry/letter.txt"]


def test_ingest_refuses_to_store_mismatched_vectors(tmp_path):
    """Guards the provider quirk where a batch of N returns a single vector."""

    class BadEmbedder(HashEmbedder):
        def embed_documents(self, texts):
            return [self.embed_query(texts[0])]

    matter = _matter(tmp_path, {"letter.txt": "פסקה אחת. " * 200 + "\n\n" + "פסקה שתיים. " * 200})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        with pytest.raises(RuntimeError, match="refusing to store mismatched"):
            ingest_matter(matter, store, BadEmbedder(), log=lambda _: None)


# ---------------------------------------------------------------------- search

def test_lexical_search_finds_an_exact_visa_class(tmp_path):
    matter = _matter(
        tmp_path,
        {
            "work.txt": "הבקשה שהוגשה היא לאשרת עבודה מסוג ב/1 בהתאם לנוהל. " * 6,
            "spouse.txt": "ההליך המדורג מעניק מעמד א/5 לבן זוג של אזרח ישראלי. " * 6,
        },
    )
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        hits = search(store, matter.slug, "מה המשמעות של מעמד א/5", HashEmbedder(), top_k=1)
    assert hits[0].rel_path == "spouse.txt"


def test_search_returns_a_citation_for_each_hit(tmp_path):
    matter = _matter(tmp_path, {"letter.txt": "אשרת חוזר ובקשת מקלט " * 60})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, HashEmbedder(), log=lambda _: None)
        hits = search(store, matter.slug, "אשרת חוזר", HashEmbedder(), top_k=2)
    assert all(hit.citation.startswith("letter.txt#") for hit in hits)
    assert all(hit.found_by in {"both", "wording", "meaning"} for hit in hits)


def test_search_on_an_empty_matter_returns_nothing(tmp_path):
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        assert search(store, "nobody", "שאלה", HashEmbedder()) == []


def test_a_dimension_change_raises_instead_of_ranking_nonsense(tmp_path):
    matter = _matter(tmp_path, {"letter.txt": "אשרת חוזר " * 60})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, HashEmbedder(dimensions=64), log=lambda _: None)
        with pytest.raises(ValueError, match="Re-run ingest"):
            search(store, matter.slug, "אשרת חוזר", HashEmbedder(dimensions=32))


def test_lexical_only_search_works_without_an_embedder(tmp_path):
    matter = _matter(tmp_path, {"letter.txt": "בקשה לאשרת חוזר עבור אנה " * 60})
    with ChunkStore(tmp_path / "index.sqlite3") as store:
        ingest_matter(matter, store, None, log=lambda _: None)
        hits = search(store, matter.slug, "אשרת חוזר", None, top_k=2)
    assert hits and all(hit.vector_rank is None for hit in hits)


def test_unit_normalises_and_tolerates_a_zero_vector():
    assert np.isclose(np.linalg.norm(unit([3.0, 4.0])), 1.0)
    assert float(np.linalg.norm(unit([0.0, 0.0]))) == 0.0
