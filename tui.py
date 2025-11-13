#!/usr/bin/env python3
"""WorkWeek TUI - Phase 2.1 starter

This is a minimal Textual app that loads tasks from `workweek.py` and
renders a simple, scrollable placeholder view. It provides a clean
starting point for building the 14-day layout and keyboard interactions.

Run with:

  python tui.py

Keys:
  q / Ctrl-C  Quit
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

try:
    # import shared logic from workweek (safe because workweek only declares Typer commands)
    from workweek import load_tasks, Task
except Exception:
    # fallback: if import fails, try to load schedule.json directly
    load_tasks = None
    Task = None

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static, ScrollView


class PlaceholderView(Static):
    """A widget that renders a two-week placeholder view using Rich tables."""

    def __init__(self, tasks: List[Task] | None = None) -> None:
        super().__init__()
        self.tasks = tasks or []

    def render(self):
        now = datetime.now()
        end = now + timedelta(days=13)

        table = Table.grid(expand=True)
        table.add_column("Day", ratio=1)
        table.add_column("Tasks", ratio=4)

        # build dataset: group tasks by date
        days = []
        for d in range(0, 14):
            dt = (now + timedelta(days=d)).date()
            days.append(dt)

        tasks_by_date = {d: [] for d in days}
        unscheduled = []
        for t in (self.tasks or []):
            when = getattr(t, "when", None)
            if when:
                date_key = when.date()
                if date_key in tasks_by_date:
                    tasks_by_date[date_key].append(t)
            else:
                unscheduled.append(t)

        # unscheduled first
        unsched_text = Text()
        if unscheduled:
            for t in unscheduled:
                unsched_text.append(f"• {t.id}: {t.title} \n", style="bold green")
        else:
            unsched_text.append("(none)\n", style="dim")

        table.add_row("Unscheduled", unsched_text)

        for d in days:
            day_name = d.strftime("%a %b %d")
            if d == now.date():
                day_name += " (Today)"
            col_text = Text()
            ts = tasks_by_date.get(d, [])
            if ts:
                for t in ts:
                    time_str = t.when.strftime("%I:%M %p") if getattr(t, "when", None) else ""
                    cat = f"[{t.category}] " if getattr(t, "category", None) else ""
                    col_text.append(f"{time_str} {cat}{t.title}\n")
            else:
                col_text.append("-\n", style="dim")

            table.add_row(day_name, col_text)

        panel = Panel(table, title="WorkWeek — 14-day placeholder", border_style="cyan")
        return panel


class WorkWeekTUI(App):
    CSS = """
    Screen {
        align: center middle;
    }
    #container {
        width: 90%;
        height: 90%;
    }
    """

    BINDINGS = [("q", "quit", "Quit"), ("ctrl+c", "quit", "Quit")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        # load tasks from workweek if available
        tasks = []
        if load_tasks:
            try:
                tasks = load_tasks()
            except Exception:
                tasks = []

        yield ScrollView(PlaceholderView(tasks), id="container")
        yield Footer()


if __name__ == "__main__":
    WorkWeekTUI().run()
