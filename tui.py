#!/usr/bin/env python3
"""WorkWeek TUI — Phase 2.2 starter

This TUI implements a simple 14-day column layout with keyboard
navigation and basic actions (toggle done, delete). It is intentionally
lightweight: the UI re-renders the grid on state changes.

Keys:
  Left / Right   Move between day columns
  Up / Down      Move between tasks in the focused column
  Enter          Toggle done for selected task
  d              Delete selected task (press 'y' to confirm)
  q / Ctrl-C     Quit
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, Static
from textual.scroll_view import ScrollView
from textual.binding import Binding

try:
    # load persistence helpers from workweek
    from workweek import load_tasks, save_tasks, Task, parse_datetime
    import tempfile
    import json
    import os
    import subprocess
except Exception:
    raise


class GridView(Static):
    """Renders the 14-day grid as a Rich Panel containing a Table.

    Accepts an optional `pending_delete` tuple so the UI can render a
    centered confirmation prompt.
    """

    def __init__(self, tasks: List[Task], focus_col: int, selection: Dict[int, int], pending_delete: Optional[Tuple[int, int]] = None) -> None:
        super().__init__()
        self.tasks = tasks
        self.focus_col = focus_col
        self.selection = selection
        self.pending_delete = pending_delete

    def render(self):
        now = datetime.now()
        # build 14-day window starting today
        days = [(now + timedelta(days=d)).date() for d in range(0, 14)]

        # group tasks by date (None -> unscheduled)
        from collections import defaultdict

        by_date = defaultdict(list)
        unscheduled = []
        for t in self.tasks:
            if t.when:
                by_date[t.when.date()].append(t)
            else:
                unscheduled.append(t)

        # Build a grid table with 15 columns: Unscheduled + 14 days
        cols = ["Unscheduled"] + [d.strftime("%a %b %d") for d in days]
        table = Table.grid(expand=True)
        for _ in cols:
            table.add_column(ratio=1)

        cells: List[Text] = []
        # Unscheduled column
        unsched_text = Text()
        if unscheduled:
            for i, t in enumerate(unscheduled):
                sel = self.selection.get(0)
                marker = "▶ " if sel == i and self.focus_col == 0 else "  "
                done = "[dim][done][/dim] " if t.done else ""
                # color-code categories
                cat = ""
                if t.category:
                    cmap = {"work": "blue", "school": "green", "personal": "magenta"}
                    col = cmap.get(t.category.lower(), "white")
                    cat = f"[{col}]{t.category}[/] "
                unsched_text.append(f"{marker}{t.id}: {cat}{t.title} {done}\n")
        else:
            unsched_text.append("(none)\n", style="dim")
        cells.append(unsched_text)

        # Day columns
        for col_idx, d in enumerate(days, start=1):
            ts = sorted(by_date.get(d, []), key=lambda x: x.when or datetime.min)
            col_text = Text()
            if ts:
                for i, t in enumerate(ts):
                    sel = self.selection.get(col_idx)
                    marker = "▶ " if sel == i and self.focus_col == col_idx else "  "
                    time_str = t.when.strftime("%I:%M %p") if t.when else ""
                    done = "[dim][done][/dim] " if t.done else ""
                    cat = ""
                    if t.category:
                        cmap = {"work": "blue", "school": "green", "personal": "magenta"}
                        col = cmap.get(t.category.lower(), "white")
                        cat = f"[{col}]{t.category}[/] "
                    col_text.append(f"{marker}{time_str:8} {t.id}: {cat}{t.title} {done}\n")
            else:
                col_text.append("-\n", style="dim")
            cells.append(col_text)

        # Add the single-row of panels to the table
        panels = [Panel(cells[i], title=cols[i], border_style=("bold magenta" if i == self.focus_col else "cyan")) for i in range(len(cols))]
        table.add_row(*panels)

        # If a delete is pending, render a confirmation prompt above the table
        if self.pending_delete is not None:
            prompt = Text("Confirm delete? Press 'y' to confirm, Esc to cancel", style="bold red")
            wrapper = Table.grid(expand=True)
            wrapper.add_column()
            wrapper.add_row(Panel(prompt, border_style="red"))
            wrapper.add_row(Panel(table, title="WorkWeek — 14-day view", border_style="green"))
            return Panel(wrapper, border_style="yellow")

        return Panel(table, title="WorkWeek — 14-day view", border_style="green")


class WorkWeekTUI(App):
    CSS = """
    Screen { align: center middle; }
    #container { width: 95%; height: 95%; }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("left", "left", "Left"),
        Binding("right", "right", "Right"),
        Binding("up", "up", "Up"),
        Binding("down", "down", "Down"),
        Binding("enter", "toggle_done", "Toggle Done"),
        Binding("d", "delete", "Delete"),
        Binding("y", "confirm", "Confirm"),
        Binding("e", "edit", "Edit"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollView(id="main")
        yield Footer()

    def on_mount(self) -> None:
        # state
        self.tasks: List[Task] = load_tasks()
        # focus_col: 0 => Unscheduled, 1..14 => days
        self.focus_col: int = 0
        # selection index per column
        self.selection: Dict[int, int] = {}
        self.pending_delete: Optional[Tuple[int, int]] = None
        self.refresh_main()

    # helpers
    def refresh_main(self) -> None:
        main = self.query_one("#main", ScrollView)
        main.update(GridView(self.tasks, self.focus_col, self.selection, pending_delete=self.pending_delete))

    def _tasks_for_col(self, col: int) -> List[Task]:
        now = datetime.now()
        days = [(now + timedelta(days=d)).date() for d in range(0, 14)]
        if col == 0:
            return [t for t in self.tasks if t.when is None]
        else:
            day = days[col - 1]
            return sorted([t for t in self.tasks if t.when and t.when.date() == day], key=lambda x: x.when)

    def action_left(self) -> None:
        self.focus_col = max(0, self.focus_col - 1)
        self.refresh_main()

    def action_right(self) -> None:
        self.focus_col = min(14, self.focus_col + 1)
        self.refresh_main()

    def action_up(self) -> None:
        tasks = self._tasks_for_col(self.focus_col)
        if not tasks:
            return
        idx = self.selection.get(self.focus_col, 0)
        idx = max(0, idx - 1)
        self.selection[self.focus_col] = idx
        self.refresh_main()

    def action_down(self) -> None:
        tasks = self._tasks_for_col(self.focus_col)
        if not tasks:
            return
        idx = self.selection.get(self.focus_col, 0)
        idx = min(len(tasks) - 1, idx + 1)
        self.selection[self.focus_col] = idx
        self.refresh_main()

    def action_toggle_done(self) -> None:
        tasks = self._tasks_for_col(self.focus_col)
        if not tasks:
            return
        idx = self.selection.get(self.focus_col, 0)
        t = tasks[idx]
        t.done = not t.done
        save_tasks(self.tasks)
        self.refresh_main()

    def action_delete(self) -> None:
        tasks = self._tasks_for_col(self.focus_col)
        if not tasks:
            return
        idx = self.selection.get(self.focus_col, 0)
        # set pending; require 'y' to confirm
        self.pending_delete = (self.focus_col, idx)
        footer = self.query_one(Footer)
        footer.update(Text("Press 'y' to confirm delete, any other key to cancel", style="bold red"))

    def action_edit(self) -> None:
        """Open the selected task in $EDITOR for editing (title/when/category).

        We write a small JSON file with fields title/when/category, open the
        user's editor, and then read back changes and apply them. This keeps
        text editing simple and leverages the user's editor for speed.
        """
        tasks = self._tasks_for_col(self.focus_col)
        if not tasks:
            return
        idx = self.selection.get(self.focus_col, 0)
        if idx >= len(tasks):
            return
        t = tasks[idx]

        # prepare temp file
        with tempfile.NamedTemporaryFile("w+", delete=False, suffix=".json") as tf:
            tmp_path = tf.name
            payload = {
                "id": t.id,
                "title": t.title,
                "when": t.when.isoformat() if t.when else "",
                "category": t.category or "",
            }
            tf.write(json.dumps(payload, indent=2))
            tf.flush()

        editor = os.environ.get("EDITOR", "vi")
        try:
            # open editor in the terminal; this will block until the editor exits
            subprocess.run([editor, tmp_path])
        except Exception as e:
            footer = self.query_one(Footer)
            footer.update(Text(f"Editor launch failed: {e}", style="bold red"))
            return

        # read back file and apply changes
        try:
            with open(tmp_path, "r") as f:
                data = json.load(f)
        except Exception as e:
            footer = self.query_one(Footer)
            footer.update(Text(f"Failed to read edited file: {e}", style="bold red"))
            return
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        # apply edits
        # find task in global list by id
        for global_t in self.tasks:
            if global_t.id == data.get("id"):
                global_t.title = data.get("title", global_t.title)
                cat = data.get("category")
                global_t.category = cat if cat != "" else None
                when_str = data.get("when")
                if when_str:
                    parsed = parse_datetime(when_str)
                    if parsed:
                        global_t.when = parsed
                    else:
                        # try ISO parse
                        try:
                            global_t.when = datetime.fromisoformat(when_str)
                        except Exception:
                            # leave unchanged if cannot parse
                            pass
                else:
                    global_t.when = None
                break

        save_tasks(self.tasks)
        self.refresh_main()

    def action_confirm(self) -> None:
        if not self.pending_delete:
            return
        col, idx = self.pending_delete
        tasks = self._tasks_for_col(col)
        if not tasks or idx >= len(tasks):
            self.pending_delete = None
            self.refresh_main()
            return
        t = tasks[idx]
        # remove from global tasks list
        self.tasks = [x for x in self.tasks if x.id != t.id]
        save_tasks(self.tasks)
        self.pending_delete = None
        # clear footer
        footer = self.query_one(Footer)
        footer.update(Text(""))
        self.refresh_main()

    def action_cancel(self) -> None:
        """Cancel any pending action (e.g., delete confirmation)."""
        self.pending_delete = None
        footer = self.query_one(Footer)
        footer.update(Text(""))
        self.refresh_main()


if __name__ == "__main__":
    WorkWeekTUI().run()
