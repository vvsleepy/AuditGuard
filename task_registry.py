import json
import os
import random


DATA_DIR = "data"


def list_tasks():
    return [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]


def load_task(task_id):
    path = os.path.join(DATA_DIR, f"{task_id}.json")
    with open(path, "r") as f:
        return json.load(f)


def get_random_task(difficulty=None):
    tasks = list_tasks()
    if difficulty:
        tasks = [t for t in tasks if difficulty in t]
    task_file = random.choice(tasks)
    with open(os.path.join(DATA_DIR, task_file)) as f:
        return json.load(f)
