#!/usr/bin/env python3
"""WorkWeek Scheduler CLI - starter Typer app"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer
from pydantic import BaseModel, Field
from rich import print

app = typer.Typer()

# store schedule.json in the user's home directory by default
DATA_FILE = Path.home() / "schedule.json"


class Task(BaseModel):
    """Pydantic Task model.

    - `when` uses a datetime when provided (ISO strings are accepted in JSON).
    - `created_at` is set automatically.
    """

    id: int
    title: str = Field(..., min_length=1)
    when: Optional[datetime] = None
    category: Optional[str] = None
    done: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Pydantic v2 configuration
    model_config = {"extra": "forbid"}


def _task_to_serializable(t: Task) -> dict:
    d = t.model_dump()
    # convert datetimes to ISO strings for JSON
    for k in ("when", "created_at"):
        if k in d and isinstance(d[k], datetime):
            d[k] = d[k].isoformat()
    return d


def save_tasks(tasks: List[Task]) -> None:
    """Atomically save tasks to `DATA_FILE` as JSON.

    Writes to a temp file first then replaces the target file. Creates
    the parent directory if needed.
    """
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = [_task_to_serializable(t) for t in tasks]

    # use a temp file in the same directory for atomic replace
    with tempfile.NamedTemporaryFile("w", delete=False, dir=str(DATA_FILE.parent)) as tf:
        tf.write(json.dumps(data, indent=2))
        tmp_path = Path(tf.name)

    # move into place (atomic on most OSes)
    shutil.move(str(tmp_path), str(DATA_FILE))


def load_tasks() -> List[Task]:
    """Load tasks from `DATA_FILE`.

    If the file doesn't exist an empty list is returned. If the JSON is
    corrupted the file is backed up to `schedule.json.corrupt.<ts>` and an
    empty list is returned so the app can continue.
    """
    if not DATA_FILE.exists():
        return []
    try:
        raw = DATA_FILE.read_text()
        data = json.loads(raw)
        tasks: List[Task] = []
        for item in data:
            # normalize ISO datetimes to datetime objects where possible
            if "when" in item and item["when"]:
                try:
                    item["when"] = datetime.fromisoformat(item["when"])
                except Exception:
                    # fallback: leave as-is (or None)
                    item["when"] = None
            if "created_at" in item and item["created_at"]:
                try:
                    item["created_at"] = datetime.fromisoformat(item["created_at"])
                except Exception:
                    item["created_at"] = datetime.utcnow()
            tasks.append(Task(**item))
        return tasks
    except json.JSONDecodeError:
        # backup the corrupt file and return an empty list
        ts = int(datetime.utcnow().timestamp())
        backup = DATA_FILE.with_name(f"{DATA_FILE.name}.corrupt.{ts}")
        shutil.copy2(DATA_FILE, backup)
        print(f"[bold red]Corrupted schedule.json detected. Backed up to {backup} and starting fresh.[/bold red]")
        return []
    except Exception as e:
        print(f"[bold red]Error loading tasks:[/bold red] {e}")
        raise


@app.command()
def add(title: str = typer.Argument(..., help="Task title")):
    """Fast add a task. Natural language parsing will be added later."""
    tasks = load_tasks()
    next_id = (max((t.id for t in tasks), default=0) + 1) if tasks else 1
    task = Task(id=next_id, title=title)
    tasks.append(task)
    save_tasks(tasks)
    print(f"[green]Added task {task.id}:[/green] {task.title}")


@app.command()
def view(days: int = 14):
    """View tasks for next `days` days (default 14)."""
    tasks = load_tasks()
    if not tasks:
        print("No tasks found.")
        raise typer.Exit()
    print(f"Showing next {days} days (placeholder)")
    for t in tasks:
        print(f"{t.id}: {t.title} {'[done]' if t.done else ''}")


if __name__ == "__main__":
    app()
