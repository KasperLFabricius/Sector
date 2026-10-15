from types import SimpleNamespace

from app import help_navigation


def test_parent_topic_includes_its_subsections_and_stops_at_next_peer():
    entries = [SimpleNamespace(block=block) for block in [
        ("h1", "First"), ("md", "Introduction"), ("h2", "Child"),
        ("md", "Input explanation"), ("h3", "Detail"), ("md", "Detail text"),
        ("h2", "Sibling"), ("h1", "Next"),
    ]]
    index = help_navigation.sections({"Part": entries})
    assert [(item["start"], item["end"]) for item in index] == [(0, 7), (2, 6), (4, 6), (6, 7), (7, 8)]
    assert "Input explanation" in index[0]["text"]
    assert "Next" not in index[0]["text"]


def test_every_page_help_resolves_to_one_published_manual_topic():
    from app import manual

    index = help_navigation.sections(manual.manual_published_item_parts())
    assert set(help_navigation.PAGE_HELP) == set(help_navigation.PAGE_DESTINATIONS)
    for page in (*help_navigation.PAGE_HELP, "result-status"):
        topic = help_navigation.requested_topic(index, page)
        assert topic is not None, page
        assert sum(entry["title"] == topic["title"] for entry in index) == 1
    assert help_navigation.requested_topic(index, "untrusted-route") is None
