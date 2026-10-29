from pathlib import Path
import importlib
from typing import Any

from claim_chain.documents import DocumentStore

pymupdf: Any = importlib.import_module("pymupdf")


def test_ingests_sources_and_returns_search_snippets_and_passages(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    nested = documents / "nested"
    nested.mkdir(parents=True)
    (nested / "guide.md").write_text("First paragraph.\n\nEvidence lives here.", encoding="utf-8")
    (documents / "page.html").write_text(
        "<nav>menu links</nav><h1>Title</h1><p>Useful HTML evidence.</p><script>hidden token</script>",
        encoding="utf-8",
    )
    store = DocumentStore(documents, tmp_path / "archive")

    listed = store.list_sources()["sources"]
    assert len(listed) == 2
    markdown = next(source for source in listed if source["title"] == "guide.md")
    assert markdown["year"] == 0
    assert markdown["passages"] == []
    assert markdown["manifest"]["chunk_count"] == 1
    assert markdown["manifest"]["path"] == "nested/guide.md"
    assert len(markdown["manifest"]["content_hash"]) == 64
    assert (tmp_path / "archive" / markdown["id"] / "guide.md").is_file()

    matches = store.search_source(markdown["id"], "Evidence", limit=5)["matches"]
    assert len(matches) == 1
    assert "Evidence lives here." in matches[0]["snippet"]
    assert "text" not in matches[0]

    passages = store.read_source(markdown["id"], start=matches[0]["chunk"])["passages"]
    assert passages == [
        {
            "id": matches[0]["id"],
            "chunk": matches[0]["chunk"],
            "locator": "text, chunk 1",
            "text": "First paragraph.\nEvidence lives here.",
        }
    ]
    html_source = next(source for source in listed if source["title"] == "page.html")
    html_text = store.read_source(html_source["id"])["passages"][0]["text"]
    assert "hidden" not in html_text
    assert "menu links" not in html_text


def test_pdf_passages_keep_page_locations(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    pdf_path = documents / "report.pdf"
    with pymupdf.open() as document:
        first = document.new_page()
        first.insert_text((72, 72), "Alpha page evidence")
        second = document.new_page()
        second.insert_text((72, 72), "Beta page evidence")
        document.new_page()
        document.save(pdf_path)

    store = DocumentStore(documents, tmp_path / "archive")
    source = store.sources[0]
    result = store.read_source(source.id, count=2)["passages"]
    assert [passage["locator"] for passage in result] == ["page 1, chunk 1", "page 2, chunk 1"]
    assert [passage["text"].strip() for passage in result] == [
        "Alpha page evidence",
        "Beta page evidence",
    ]
    manifest = store.list_sources()["sources"][0]["manifest"]
    assert manifest["blank_pages"] == 1
    assert "1 PDF page" in manifest["warning"]


def test_extraction_failure_is_reported_without_skipping_other_sources(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "broken.pdf").write_bytes(b"not a PDF")
    (documents / "notes.txt").write_text("Available evidence.", encoding="utf-8")
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(documents / "scanned.pdf")

    store = DocumentStore(documents, tmp_path / "archive")
    sources = store.list_sources()["sources"]
    broken = next(source for source in sources if source["title"] == "broken.pdf")
    scanned = next(source for source in sources if source["title"] == "scanned.pdf")
    available = next(source for source in sources if source["title"] == "notes.txt")

    assert "error" in broken["manifest"]
    assert broken["manifest"]["chunk_count"] == 0
    assert "scanned or blank" in scanned["manifest"]["error"]
    assert scanned["manifest"]["page_count"] == 1
    assert store.read_source(available["id"])["passages"][0]["text"] == "Available evidence."


def test_changed_content_gets_new_source_identity_and_read_count_is_bounded(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    source_path = documents / "long.txt"
    source_path.write_text("\n".join(f"needle {index} " + "x" * 3000 for index in range(12)), encoding="utf-8")
    archive = tmp_path / "archive"

    first_store = DocumentStore(documents, archive)
    first_id = first_store.sources[0].id
    assert len(first_store.search_source(first_id, "needle", limit=50)["matches"]) == 10
    assert len(first_store.read_source(first_id, count=50)["passages"]) == 3

    source_path.write_text("replacement", encoding="utf-8")
    second_store = DocumentStore(documents, archive)
    assert second_store.sources[0].id != first_id
    assert second_store.list_sources()["sources"][0]["manifest"]["chunk_count"] == 1


def test_archive_cannot_be_nested_in_documents(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()

    try:
        DocumentStore(documents, documents / "archive")
    except ValueError as error:
        assert "outside" in str(error)
    else:
        raise AssertionError("Nested archive should be rejected")


def test_metadata_file_supplies_edition_and_year(tmp_path: Path) -> None:
    documents = tmp_path / "documents"
    documents.mkdir()
    (documents / "register.md").write_text("Entry.", encoding="utf-8")
    (documents / "metadata.json").write_text(
        '{"register.md": {"edition": "first edition", "year": 1923}}', encoding="utf-8"
    )
    [source] = DocumentStore(documents, tmp_path / "archive").list_sources()["sources"]
    assert (source["edition"], source["year"]) == ("first edition", 1923)
