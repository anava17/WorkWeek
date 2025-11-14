#!/usr/bin/env python3
"""WorkWeek Scheduler CLI - starter Typer app"""
from __future__ import annotations

import json
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import parsedatetime as pdt
import typer
from dateutil import parser as dateutil_parser
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

    id: str
    title: str = Field(..., min_length=1)
    when: Optional[datetime] = None
    category: Optional[str] = None
    done: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Pydantic v2 configuration
    model_config = {"extra": "forbid"}


def parse_datetime(date_str: str) -> Optional[datetime]:
    """Parse a natural language date string into a datetime object.

    Supports formats like:
    - "tomorrow @ 9am"
    - "next monday"
    - "in 3 days"
    - "2025-11-15"
    - "11/15/2025 2pm"

    Returns None if parsing fails.
    """
    if not date_str or not date_str.strip():
        return None

    # try parsedatetime first (handles relative dates well)
    cal = pdt.Calendar()
    try:
        dt, parse_status = cal.parseDT(date_str, sourceTime=datetime.now())
        # parse_status: 0=no match, 1=date match, 2=time match, 3=both
        if parse_status > 0:
            return dt
    except Exception:
        pass

    # fall back to dateutil parser (handles ISO & other formats)
    try:
        return dateutil_parser.parse(date_str, fuzzy=False)
    except Exception:
        pass

    return None


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
            # Convert integer id to string for backward compatibility
            if "id" in item and isinstance(item["id"], int):
                item["id"] = str(item["id"])
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
def add(
    title: str = typer.Argument(..., help="Task title"),
    when: Optional[str] = typer.Option(None, "--when", "-w", help="When to schedule (e.g., 'tomorrow @ 9am', 'next monday')"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Task category (e.g., 'Work', 'School')"),
):
    """Fast add a task with optional natural language date parsing.

    Examples:
      workweek add "Design mockups" --when "tomorrow @ 2pm" --category "Work"
      workweek add "Study for exam" --when "next friday"
      workweek add "Quick task"  (no date specified)
    """
    tasks = load_tasks()
    next_id = (max((t.id for t in tasks), default=0) + 1) if tasks else 1

    # parse the when date if provided
    parsed_when = None
    if when:
        parsed_when = parse_datetime(when)
        if not parsed_when:
            print(f"[bold red]Could not parse date:[/bold red] '{when}' (try 'tomorrow @ 9am', 'next monday', etc.)")
            raise typer.Exit(code=1)

    task = Task(id=next_id, title=title, when=parsed_when, category=category)
    tasks.append(task)
    save_tasks(tasks)

    when_str = f" → {parsed_when.strftime('%a, %b %d @ %I:%M %p')}" if parsed_when else ""
    cat_str = f" [{category}]" if category else ""
    print(f"[green]Added task {task.id}:{cat_str}[/green] {task.title}{when_str}")


@app.command()
def view(days: int = typer.Option(14, "--days", "-d", help="Number of days to show (default 14)")):
    """View tasks for the next N days, grouped by date.

    Shows unscheduled tasks first, then organizes scheduled tasks by day.
    """
    tasks = load_tasks()
    if not tasks:
        print("[dim]No tasks found.[/dim]")
        raise typer.Exit()

    now = datetime.now()
    end_date = now + timedelta(days=days)

    # partition tasks into unscheduled and scheduled
    unscheduled = [t for t in tasks if t.when is None]
    scheduled = [t for t in tasks if t.when is not None and t.when <= end_date]

    # show unscheduled tasks first
    if unscheduled:
        print("\n[bold cyan]Unscheduled[/bold cyan]")
        for t in unscheduled:
            status = "[dim][done][/dim]" if t.done else ""
            cat = f"[{t.category}] " if t.category else ""
            print(f"  {t.id:2}. {cat}{t.title} {status}")

    # group scheduled tasks by date
    from collections import defaultdict
    by_date = defaultdict(list)
    for t in scheduled:
        if t.when:
            date_key = t.when.date()
            by_date[date_key].append(t)

    # sort dates and display
    if by_date:
        print()
        for date_key in sorted(by_date.keys()):
            tasks_on_day = by_date[date_key]
            day_name = date_key.strftime("%a, %b %d")
            days_away = (date_key - now.date()).days
            if days_away == 0:
                day_name += " (Today)"
            elif days_away == 1:
                day_name += " (Tomorrow)"
            elif days_away > 1 and days_away <= 7:
                day_name += f" (+{days_away}d)"

            print(f"[bold yellow]{day_name}[/bold yellow]")
            for t in tasks_on_day:
                time_str = t.when.strftime("%I:%M %p") if t.when else ""
                status = "[dim][done][/dim]" if t.done else ""
                cat = f"[{t.category}] " if t.category else ""
                print(f"  {t.id:2}. {time_str:12} {cat}{t.title} {status}")

    print()  # blank line at end


if __name__ == "__main__":
    app()
