from staffing_agent.google_docs_fetch import (
    google_doc_id_from_url,
    plain_text_from_document_resource,
)


def test_google_doc_id_from_url():
    assert (
        google_doc_id_from_url(
            "https://docs.google.com/document/d/1abcXYZ/edit?usp=sharing"
        )
        == "1abcXYZ"
    )
    assert google_doc_id_from_url("https://example.com/doc") is None


def test_plain_text_from_minimal_doc_body():
    doc = {
        "title": "T",
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Hello "}}, {"textRun": {"content": "world"}}],
                    }
                }
            ]
        },
    }
    assert "Hello" in plain_text_from_document_resource(doc)
    assert "world" in plain_text_from_document_resource(doc)
