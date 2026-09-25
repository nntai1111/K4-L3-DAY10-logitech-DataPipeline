"""The Phase 3 check commands in the lab handout (1.docx) use a different API from the starter's
docs. These tests run the handout's calls as written, against a temp project."""

from __future__ import annotations

from core.utils import write_json
from evaluation.testset import load_or_create_test_set
from retrieval.index import LocalEmbeddingIndex


def test_handout_index_command_builds_and_searches(settings, clean_df):
    write_json(settings.paths.clean_json, clean_df.to_dict(orient="records"))

    index = LocalEmbeddingIndex(settings, collection_name="papers-baseline")
    assert index.documents == []  # nothing built yet
    index.build_from_clean()
    results = index.semantic_search("machine learning", top_k=2)

    assert len(results) == 2
    assert len(index.documents) == len(clean_df)
    assert settings.paths.embeddings_json.exists()


def test_handout_index_reopens_a_built_collection(settings, clean_df):
    write_json(settings.paths.clean_json, clean_df.to_dict(orient="records"))
    LocalEmbeddingIndex(settings, collection_name="papers-baseline").build_from_clean()

    reopened = LocalEmbeddingIndex(settings, collection_name="papers-baseline")

    assert len(reopened.documents) == len(clean_df)
    assert reopened.lookup(clean_df.iloc[0]["paper_id"]) is not None


def test_handout_testset_command(settings, clean_df):
    test_set = load_or_create_test_set(clean_df, settings.paths.test_set_json)

    assert len(test_set.samples) == 10
    assert settings.paths.test_set_json == settings.paths.eval_testset
