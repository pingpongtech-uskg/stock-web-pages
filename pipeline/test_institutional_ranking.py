from pipeline.institutional_ranking import annotate_top_n_entries


def test_annotate_top10_marks_only_codes_not_in_previous_top10():
    previous = [
        {"rank": 1, "code": "A"},
        {"rank": 2, "code": "B"},
        {"rank": 3, "code": "C"},
        {"rank": 4, "code": "D"},
        {"rank": 5, "code": "E"},
        {"rank": 6, "code": "F"},
        {"rank": 7, "code": "G"},
        {"rank": 8, "code": "H"},
        {"rank": 9, "code": "I"},
        {"rank": 10, "code": "J"},
        {"rank": 11, "code": "K"},
    ]
    current = [
        {"rank": 1, "code": "K"},
        {"rank": 2, "code": "A"},
        {"rank": 3, "code": "L"},
        {"rank": 4, "code": "B"},
    ]

    result = annotate_top_n_entries(current, previous, limit=10)

    assert [(row["code"], row["entryStatus"], row["previousRank"]) for row in result] == [
        ("K", "new", 11),
        ("A", "retained", 1),
        ("L", "new", None),
        ("B", "retained", 2),
    ]


def test_annotate_top10_does_not_claim_new_when_previous_snapshot_missing():
    current = [{"rank": 1, "code": "A"}, {"rank": 2, "code": "B"}]

    result = annotate_top_n_entries(current, [], limit=10)

    assert [(row["code"], row["entryStatus"], row["previousRank"]) for row in result] == [
        ("A", "unknown", None),
        ("B", "unknown", None),
    ]


def test_annotate_top10_limits_to_top_n_and_reassigns_display_rank():
    current = [{"rank": 20, "code": "Z"}, {"rank": 3, "code": "C"}, {"rank": 1, "code": "A"}]

    result = annotate_top_n_entries(current, [], limit=2)

    assert [(row["code"], row["rank"], row["sourceRank"]) for row in result] == [
        ("A", 1, 1),
        ("C", 2, 3),
    ]
