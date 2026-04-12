def test_task_loading():
    from task_registry import list_tasks

    tasks = list_tasks()
    assert len(tasks) >= 3
