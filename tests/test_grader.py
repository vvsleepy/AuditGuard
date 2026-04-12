def test_grader_score_bounds():
    from graders import grade_episode

    score = grade_episode(
        {},
        {"violations": [], "clean_items": [], "final_decision": ""},
        {"approvals": [], "requests": [], "final_decision": "", "steps": 1, "max_steps": 10},
    )
    assert 0.0 < score < 1.0
