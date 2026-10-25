from clausecheck.core import schema


def test_schema_constants():
    assert len(schema.MANIFEST_COLUMNS) == len(set(schema.MANIFEST_COLUMNS))
    for col in ["doc_id", "supplier_id", "source", "doc_type", "format", "path",
                "parent_doc_id", "licence", "sha256", "is_synthetic"]:
        assert col in schema.MANIFEST_COLUMNS
    assert {"pdf", "html", "docx", "txt"} <= schema.FORMATS
    assert "synthetic" in schema.SOURCES
    assert schema.AMENDMENT_TYPES <= schema.DOC_TYPES
