"""Smoke assertions must match the callback delivery contract."""

import pytest

from scripts.local_smoke.extraction_matrix import check_callbacks


def test_callbacks_allow_reordered_delivery_but_require_all_events(monkeypatch):
    monkeypatch.setattr(
        "scripts.local_smoke.extraction_matrix.time.sleep", lambda _: None
    )
    events = [
        {"kind": "task_completed", "progress": {}},
        {
            "kind": "document_completed",
            "progress": {"document": {"source": "a.pdf"}},
            "artifact_present": True,
        },
        {"kind": "update_processed", "progress": {}},
        {"kind": "set_num_docs", "progress": {"num_docs": 1}},
    ]
    check_callbacks(events, 1, True)
    events[1]["artifact_present"] = False
    with pytest.raises(AssertionError, match="before its upload"):
        check_callbacks(events, 1, True)
    with pytest.raises(AssertionError, match="Expected callbacks"):
        check_callbacks(events, 2, False)
