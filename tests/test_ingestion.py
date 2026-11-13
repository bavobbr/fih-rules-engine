from unittest.mock import MagicMock, patch

import docx
import pytest

from database import PostgresVectorDB
from loaders.sequential_loader import SequentialLoader
from tests.test_rag_engine import mock_engine  # noqa: F401  (pytest fixture)


# --- SequentialLoader: Word support ---

def _make_docx(path):
    document = docx.Document()
    document.add_heading("Regel 9 Spelverloop", level=1)
    document.add_paragraph("9.12 Spelers mogen de bal niet met de voet spelen.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Kaart"
    table.cell(0, 1).text = "Duur"
    table.cell(1, 0).text = "Groen"
    table.cell(1, 1).text = "2 minuten"
    document.add_paragraph("Slotbepaling.")
    document.save(path)


def test_docx_text_and_tables_in_document_order(tmp_path):
    path = tmp_path / "upload"  # temp files from the admin page have no extension
    _make_docx(path)

    docs = SequentialLoader().load_and_chunk(str(path), "outdoor", original_filename="spelregels-bel.docx")

    text = "\n".join(d.page_content for d in docs)
    assert "9.12 Spelers mogen de bal niet met de voet spelen." in text
    assert "Groen | 2 minuten" in text
    assert text.index("Regel 9") < text.index("Kaart | Duur") < text.index("Slotbepaling.")
    assert docs[0].metadata["source_file"] == "spelregels-bel.docx"


def test_unsupported_extension_is_rejected(tmp_path):
    path = tmp_path / "upload"
    path.write_bytes(b"\xd0\xcf\x11\xe0")  # legacy .doc header
    with pytest.raises(ValueError, match="Unsupported file type"):
        SequentialLoader().load_and_chunk(str(path), "outdoor", original_filename="old.doc")


# --- Engine: per-document replace ---

def _stub_local_loader(engine):
    engine.loader_local = MagicMock()
    engine.loader_local.load_and_chunk.return_value = [MagicMock(page_content="c", metadata={})]
    engine.embeddings.embed_documents.return_value = [[0.1]]


def test_ingest_replaces_same_file_name_only(mock_engine):  # noqa: F811
    _stub_local_loader(mock_engine)

    mock_engine.ingest_pdf("/tmp/x", "indoor", country_code="BEL", original_filename="spelregels.docx")

    mock_engine.db.delete_source_file.assert_called_once_with("spelregels.docx", "indoor", country_code="BEL")


def test_ingest_also_removes_replaced_document(mock_engine):  # noqa: F811
    _stub_local_loader(mock_engine)

    mock_engine.ingest_pdf("/tmp/x", "indoor", country_code="BEL",
                           original_filename="spelregels-2026.docx", replaces="spelregels-2024.docx")

    deleted = [c.args[0] for c in mock_engine.db.delete_source_file.call_args_list]
    assert deleted == ["spelregels-2026.docx", "spelregels-2024.docx"]


def test_official_rulebook_must_be_pdf(mock_engine):  # noqa: F811
    with pytest.raises(ValueError, match="PDF"):
        mock_engine.ingest_pdf("/tmp/x", "indoor", country_code=None, original_filename="rules.docx")
    mock_engine.db.delete_source_file.assert_not_called()


# --- Database: deletes and listings are scoped ---

def _db_with_mock_conn():
    with patch.object(PostgresVectorDB, "__init__", lambda self: None):
        db = PostgresVectorDB()
    conn = MagicMock()
    db.pool = MagicMock()
    db.pool.connect.return_value.__enter__.return_value = conn
    return db, conn


def test_delete_source_file_is_scoped_to_variant_and_country():
    db, conn = _db_with_mock_conn()

    db.delete_source_file("rules.pdf", "indoor", country_code="BEL")

    stmt, params = conn.execute.call_args.args
    assert "variant = :variant" in str(stmt)
    assert "metadata->>'country' = :country" in str(stmt)
    assert params == {"filename": "rules.pdf", "variant": "indoor", "country": "BEL"}
    conn.commit.assert_called_once()


def test_delete_official_source_file_leaves_national_rules():
    db, conn = _db_with_mock_conn()

    db.delete_source_file("rules.pdf", "indoor")

    stmt, params = conn.execute.call_args.args
    assert "metadata->>'country' IS NULL" in str(stmt)
    assert params == {"filename": "rules.pdf", "variant": "indoor"}


def test_get_scope_documents():
    db, conn = _db_with_mock_conn()
    conn.execute.return_value.fetchall.return_value = [("a.docx", 312), (None, 3)]

    assert db.get_scope_documents("outdoor", country_code="BEL") == [
        {"source_file": "a.docx", "chunk_count": 312},
        {"source_file": "Unknown Source", "chunk_count": 3},
    ]
