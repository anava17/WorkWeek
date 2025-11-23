#!/usr/bin/env python3
"""WorkWeek GUI — Native windowed application using PyQt6

A calendar-style 14-day scheduler with:
- Full-screen window with day columns
- Drag-and-drop task management
- Right-click context menu (delete, edit, reschedule)
- Double-click to edit inline or open $EDITOR
- Color-coded categories (Work=blue, School=green, Personal=magenta)
- Persistent storage in schedule.json

Keys:
  Ctrl-N         New task (dialog)
  Ctrl-Q         Quit
  Delete         Delete selected task
"""
import sys
import json
import tempfile
import subprocess
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QScrollArea, QLabel, QPushButton, QDialog, QLineEdit, QDateEdit,
    QComboBox, QMessageBox, QMenu, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy
)
from PyQt6.QtCore import Qt, QDate, QDateTime, QSize, pyqtSignal, QRect, QTimer
from PyQt6.QtGui import QColor, QFont, QAction, QIcon, QPalette

from workweek import load_tasks, save_tasks, Task, parse_datetime, _occurrences_between


class FrutigerAeroStyle:
    """Defines a glossy Frutiger Aero-inspired stylesheet."""
    @staticmethod
    def get_stylesheet():
        # Frutiger Aero — glossy, airy calendar look
        return """
        QMainWindow {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 #dff7ff, stop:0.4 #cfeaff, stop:0.75 #e9e0ff, stop:1 #fbfdff);
            font-family: 'Arial', sans-serif;
        }

        /* Calendar background area */
        QScrollArea {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #f6fbff, stop:1 #eaf6ff);
        }

        /* Day column card */
        #DayColumn {
            background: rgba(255,255,255,0.95);
            border: 1px solid rgba(150,170,190,0.12);
            border-radius: 10px;
        }

        /* Day header */
        #DayHeader {
            color: #0a3142;
            padding: 10px 12px;
            font-size: 13px;
            font-weight: 800;
        }

        /* Task card (use object/class name 'taskCard') */
        QFrame.taskCard {
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                stop:0 rgba(255,255,255,0.99), stop:0.5 rgba(245,250,255,0.98), stop:1 rgba(235,245,255,0.98));
            border: 1px solid rgba(20,50,80,0.12);
            border-radius: 12px;
            padding: 10px;
            min-height: 48px;
        }

        QFrame.taskCard:hover {
            border: 1px solid rgba(26,140,255,0.28);
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 rgba(255,255,255,1), stop:1 rgba(240,250,255,1));
        }

        /* Task title style */
        QLabel#TaskTitle { color: #071622; font-weight:800; font-size:14px; }

        /* Create button accent (reused in dialog via objectName) */
        QPushButton#CreateBtn { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2aa3ff, stop:1 #007acc); color: white; border-radius: 8px; padding: 6px 12px; font-weight: 800; }

        /* Small meta chips */
        /* Time and category chips by objectName for reliability */
        QLabel#TimeChip { background: rgba(10,100,160,0.10); color: #063245; border-radius: 8px; padding: 4px 8px; font-size:11px; }
        QLabel#CatChip { background: rgba(120,90,190,0.12); color: #2b0b44; border-radius: 8px; padding: 4px 8px; font-size:11px; }

        """

    @staticmethod
    def apply_shadow(widget):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 153, 255, 60))
        widget.setGraphicsEffect(shadow)


# CategoryColumn: Kanban-style column for a category (module-level)
class CategoryColumn(QFrame):
    task_changed = pyqtSignal()
    def __init__(self, category: str, parent=None):
        super().__init__(parent)
        self.category = category
        self.tasks: List[Task] = []
        self.setup_ui()
        # avoid heavy per-column shadow effects for performance
        # FrutigerAeroStyle.apply_shadow(self)

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        # Header
        header_row = QHBoxLayout()
        header = QLabel(self.category)
        header.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        header_row.addWidget(header)
        header_row.addStretch()
        # Add button for quick create
        self.add_btn = QPushButton("+")
        self.add_btn.setFixedSize(QSize(28, 28))
        header_row.addWidget(self.add_btn)
        layout.addLayout(header_row)
        # Scrollable task area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        self.task_container = QWidget()
        self.task_layout = QVBoxLayout(self.task_container)
        self.task_layout.setSpacing(10)
        scroll.setWidget(self.task_container)
        layout.addWidget(scroll)

    def add_task(self, task: Task):
        self.tasks.append(task)
        task_widget = TaskWidget(task)
        task_widget.task_changed.connect(self._on_task_changed)
        self.task_layout.addWidget(task_widget)

    def clear_tasks(self):
        while self.task_layout.count():
            item = self.task_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.tasks.clear()

    def _on_task_changed(self):
        """Emit column-level task_changed to parent when any child widget changes."""
        self.task_changed.emit()


    @staticmethod
    def apply_shadow(widget):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(32)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 153, 255, 60))
        widget.setGraphicsEffect(shadow)


class TaskWidget(QFrame):
    """Represents a single task in the grid. Supports:
    - Right-click context menu (delete, edit)
    - Double-click to edit via $EDITOR
    - Checkbox to toggle done
    """
    
    task_changed = pyqtSignal()  # Emitted when task is modified
    
    def __init__(self, task: Task, parent=None):
        super().__init__(parent)
        self.task = task
        self.setup_ui()
        # skip applying heavy drop-shadow per task (improves UI responsiveness)
        # FrutigerAeroStyle.apply_shadow(self)
    
    def setup_ui(self):
        """Create the task display with checkbox and title."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        
        # Checkbox (done/undone)
        self.check_btn = QPushButton("✓" if self.task.done else "○")
        self.check_btn.setMaximumWidth(30)
        self.check_btn.clicked.connect(self.toggle_done)
        layout.addWidget(self.check_btn)
        
        # Title (use read-only QLineEdit for reliable layout and visibility)
        self.title_label = QLineEdit(self.task.title or "(no title)")
        self.title_label.setReadOnly(True)
        self.title_label.setFrame(False)
        # strike-through support via font when done
        if self.task.done:
            fnt = self.title_label.font()
            fnt.setStrikeOut(True)
            self.title_label.setFont(fnt)
        title_font = QFont("Arial", 12)
        self.title_label.setFont(title_font)
        self.title_label.setStyleSheet("QLineEdit { color: #071622; background: transparent; }")
        self.title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.title_label.setObjectName('TaskTitle')

        # Middle container (title + meta)
        mid = QWidget()
        mid_layout = QVBoxLayout(mid)
        mid_layout.setContentsMargins(0,0,0,0)
        mid_layout.setSpacing(4)
        mid_layout.addWidget(self.title_label)

        # meta row: category chip + small note
        meta_row = QHBoxLayout()
        meta_row.setContentsMargins(0,0,0,0)
        meta_row.setSpacing(6)
        self.cat_chip = QLabel(self.task.category or "")
        self.cat_chip.setObjectName('CatChip')
        self.cat_chip.setProperty('class', 'catChip')
        self.cat_chip.setVisible(bool(self.task.category))
        self.cat_chip.setStyleSheet("QLabel { font-size: 11px; padding: 2px 6px; border-radius:6px; background: rgba(0,0,0,0.04); color: #08314b; }")
        meta_row.addWidget(self.cat_chip)
        mid_layout.addLayout(meta_row)

        layout.addWidget(mid, 1)
        
        # Right side: time chip (format without leading zeros, e.g. '1:05 PM')
        time_text = ""
        if getattr(self.task, 'when', None):
            try:
                w = self.task.when
                h = w.hour
                m = w.minute
                hour_display = 12 if (h % 12) == 0 else (h % 12)
                period = "AM" if h < 12 else "PM"
                time_text = f"{hour_display}:{m:02d} {period}"
            except Exception:
                time_text = self.task.when.strftime('%I:%M %p')
        self.time_chip = QLabel(time_text)
        self.time_chip.setObjectName('TimeChip')
        self.time_chip.setProperty('class','timeChip')
        self.time_chip.setVisible(bool(time_text))
        self.time_chip.setStyleSheet("QLabel { font-size:11px; padding:2px 8px; border-radius:6px; background: rgba(30,120,200,0.08); color: #063245; }")
        layout.addWidget(self.time_chip)

        # Apply category color and mark as a taskCard for global QSS
        self.setObjectName('taskCard')
        self.setProperty('class', 'taskCard')
        # ensure the title label color is explicit (avoid white-on-white issues)
        self.title_label.setStyleSheet("color: #071622; background: transparent; font-weight:700;")
        # set size policy so the card expands horizontally but stays fixed vertically
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # ensure task cards have a reasonable fixed minimum height to display content
        self.setMinimumHeight(48)
        self.setStyleSheet(self._get_color_style())
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def _get_color_style(self) -> str:
        """Return stylesheet for category color with glassy/aurora effect."""
        category = self.task.category or "Personal"
        accents = {
            "Work": ("#0178d4", "#bfe7ff"),
            "School": ("#14976b", "#dcffef"),
            "Personal": ("#9b38b6", "#f7eaff")
        }
        accent_color, accent_bg = accents.get(category, ("#888888", "#f0f0f6"))
        return f"""
            QFrame {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(255,255,255,0.98), stop:1 rgba(247,252,255,0.98));
                border-radius: 10px;
                padding: 8px;
                color: #071622;
                border: 1px solid rgba(30,70,120,0.06);
            }}
            QFrame::before {{
                /* left accent simulated via border-left on the card */
            }}
            QLabel {{ color: #071622; }}
        """
    
    def toggle_done(self):
        """Toggle task done status."""
        try:
            self.task.done = not self.task.done
            self.check_btn.setText("✓" if self.task.done else "○")
            
            # Update strikethrough
            font = self.title_label.font()
            font.setStrikeOut(self.task.done)
            self.title_label.setFont(font)
            
            # Save and emit change
            self.task_changed.emit()
        except Exception as e:
            print(f"ERROR in toggle_done: {e}")
    
    def contextMenuEvent(self, event):
        """Right-click context menu."""
        menu = QMenu(self)
        
        edit_action = menu.addAction("Edit (Ctrl+E)")
        edit_action.triggered.connect(self.edit_task)

        toggle_action = menu.addAction("Toggle Done")
        toggle_action.triggered.connect(self.toggle_done)
        
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(self.delete_task)
        
        menu.exec(event.globalPos())
    
    def mouseDoubleClickEvent(self, event):
        """Double-click to edit via $EDITOR."""
        self.edit_task()
    
    def edit_task(self):
        """Edit the task inline using a modal dialog (safer than external editor)."""
        if getattr(self, '_editing', False):
            return
        self._editing = True
        try:
            # open NewTaskDialog prefilled with current task values
            when_text = ''
            try:
                if getattr(self.task, 'when', None):
                    when_text = self.task.when.strftime('%c')
            except Exception:
                when_text = ''

            dialog = NewTaskDialog(self.window(), default_category=self.task.category, default_when_text=when_text, default_title=self.task.title)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
                # update existing task fields
                updated = dialog.result_task
                self.task.title = updated.title
                self.task.category = updated.category
                self.task.when = updated.when
                self.title_label.setText(self.task.title)
                # update time chip
                if getattr(self.task, 'when', None):
                    w = self.task.when
                    h = w.hour
                    m = w.minute
                    hour_display = 12 if (h % 12) == 0 else (h % 12)
                    period = "AM" if h < 12 else "PM"
                    time_text = f"{hour_display}:{m:02d} {period}"
                    self.time_chip.setText(time_text)
                    self.time_chip.setVisible(True)
                else:
                    self.time_chip.setText("")
                    self.time_chip.setVisible(False)
                self.setStyleSheet(self._get_color_style())
                self.task_changed.emit()
        except Exception as e:
            print(f"Edit dialog failed: {e}")
        finally:
            self._editing = False
    
    def flash(self, duration: int = 700):
        """Briefly highlight the task card to indicate creation."""
        try:
            # avoid overlapping flash calls
            if getattr(self, '_flashing', False):
                return
            self._flashing = True
            orig = self.styleSheet()
            # add a glow border temporarily
            self.setStyleSheet(orig + "\nQFrame { border: 2px solid rgba(26, 140, 255, 0.9); }")
            def _end():
                try:
                    self.setStyleSheet(orig)
                finally:
                    self._flashing = False
            QTimer.singleShot(duration, _end)
        except Exception:
            pass
    def delete_task(self):
        """Emit delete request (parent handles removal)."""
        # Signal to parent to remove this task
        self.task_changed.emit()  # Parent will detect task is deleted
        self.deleteLater()


class DayColumn(QFrame):
    """Represents a single day column in the grid."""
    
    task_changed = pyqtSignal()
    
    def __init__(self, date: Optional[datetime] = None, parent=None):
        super().__init__(parent)
        self.date = date
        self.tasks: List[Task] = []
        self.setup_ui()
    
    def setup_ui(self):
        """Create the day column layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)

        # Header with date
        if self.date:
            date_str = self.date.strftime("%a %m/%d")
            today = datetime.now().date()
            if self.date.date() == today:
                date_str += " (Today)"
            elif self.date.date() == today + timedelta(days=1):
                date_str += " (Tomorrow)"
        else:
            date_str = "Unscheduled"

        header = QLabel(date_str)
        header.setObjectName('DayHeader')
        header.setFont(QFont("Arial", 12, QFont.Weight.DemiBold))
        layout.addWidget(header)

        # Scrollable area that will hold All-day section + 24 hour rows
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(6, 6, 6, 6)
        container_layout.setSpacing(6)

        # All-day area (no time) — tasks without a time go here
        self.all_day_container = QWidget()
        self.all_day_layout = QVBoxLayout(self.all_day_container)
        self.all_day_layout.setSpacing(6)
        container_layout.addWidget(self.all_day_container)

        # Hour rows: create 24 rows (00:00 - 23:00)
        self.hour_rows = []
        hours_container = QWidget()
        hours_layout = QVBoxLayout(hours_container)
        hours_layout.setContentsMargins(0, 0, 0, 0)
        hours_layout.setSpacing(0)
        for h in range(24):
            row = QFrame()
            row.setObjectName('HourRow')
            # increase row height so task cards fit without overlapping
            row.setFixedHeight(88)
            row.setFrameShape(QFrame.Shape.NoFrame)
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(6, 2, 6, 2)
            row_layout.setSpacing(4)
            # optional small hour label on left (12-hour format, no leading zero)
            hour_display = 12 if (h % 12) == 0 else (h % 12)
            period = "AM" if h < 12 else "PM"
            hour_label = QLabel(f"{hour_display}:00 {period}")
            hour_label.setStyleSheet("color: #7a8b98; font-size:11px;")
            hour_label.setFixedHeight(14)
            row_layout.addWidget(hour_label)
            hours_layout.addWidget(row)
            self.hour_rows.append(row)

        container_layout.addWidget(hours_container)

        # Make this column a fixed width like calendar columns
        self.setFixedWidth(280)
        self.setObjectName('DayColumn')

        scroll.setWidget(container)
        # allow vertical scrolling inside each day column
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(scroll)

        # Style day section for readability (leave heavy styling to global QSS)
        self.setStyleSheet("")
    
    def add_task(self, task: Task):
        """Add a task widget to this column. Place it in the hour row if it has a time, otherwise in all-day."""
        self.tasks.append(task)
        task_widget = TaskWidget(task)
        # debug: log title to help diagnose missing-label issues
        try:
            print(f"DEBUG: Adding task -> title={task.title!r}, when={getattr(task,'when',None)}, category={task.category}")
        except Exception:
            pass
        # Ensure the widget reflects the task data immediately (title and done state)
        try:
            task_widget.title_label.setText(task.title or "(no title)")
            task_widget.title_label.setVisible(True)
            task_widget.title_label.raise_()
            task_widget.title_label.setStyleSheet("color: #071622; background: transparent; font-weight:700;")
            task_widget.check_btn.setText("✓" if getattr(task, 'done', False) else "○")
            task_widget.check_btn.setEnabled(True)
        except Exception:
            pass
        task_widget.task_changed.connect(self._on_task_changed)

        # If task has a datetime with time information, place in the matching hour row
        if getattr(task, 'when', None):
            when = task.when
            if isinstance(when, datetime):
                hour = when.hour
                if 0 <= hour < len(self.hour_rows):
                    row = self.hour_rows[hour]
                    # add to this hour's layout
                    layout = row.layout()
                    if layout is None:
                        layout = QVBoxLayout(row)
                    layout.addWidget(task_widget)
                    return

        # Fallback: place in all-day container
        self.all_day_layout.addWidget(task_widget)
        # brief highlight to show newly added task
        try:
            task_widget.flash()
        except Exception:
            pass
    
    def clear_tasks(self):
        """Remove all task widgets."""
        # clear all-day area
        if hasattr(self, 'all_day_layout'):
            while self.all_day_layout.count():
                item = self.all_day_layout.takeAt(0)
                w = item.widget()
                if w:
                    w.deleteLater()
        # clear hour rows
        if hasattr(self, 'hour_rows'):
            for row in self.hour_rows:
                l = row.layout()
                if l:
                    while l.count():
                        item = l.takeAt(0)
                        w = item.widget()
                        if w:
                            w.deleteLater()
        self.tasks.clear()
    
    def _on_task_changed(self):
        """Propagate task change to parent."""
        self.task_changed.emit()

    def mouseDoubleClickEvent(self, event):
        """Double-click the day column to create a new task for that date."""
        try:
            if self.date:
                parent = self.window()
                if hasattr(parent, 'new_task_for_date'):
                    # format a friendly default when text for the dialog
                    default_when = self.date.strftime('%A %m/%d')
                    parent.new_task_for_date(self.date, default_when)
                    return
        except Exception:
            pass
        super().mouseDoubleClickEvent(event)


class NewTaskDialog(QDialog):
    """Dialog to create a new task."""
    
    def __init__(self, parent=None, default_category: Optional[str] = None, default_when_text: Optional[str] = None, default_title: Optional[str] = None):
        super().__init__(parent)
        self.setWindowTitle("New Task")
        self.setGeometry(100, 100, 420, 220)
        self.result_task = None
        self.default_category = default_category
        self.default_when_text = default_when_text
        self.default_title = default_title
        self.setup_ui()
    
    def setup_ui(self):
        """Create form widgets."""
        layout = QVBoxLayout(self)
        
        # Title
        layout.addWidget(QLabel("Title:"))
        self.title_input = QLineEdit()
        if getattr(self, 'default_title', None):
            try:
                self.title_input.setText(self.default_title)
            except Exception:
                pass
        # ensure dark text on white background for readability
        self.title_input.setStyleSheet("QLineEdit { color: #071622; background: #ffffff; }")
        layout.addWidget(self.title_input)
        
        # When (optional)
        layout.addWidget(QLabel("When (optional):"))
        self.when_input = QLineEdit()
        self.when_input.setPlaceholderText("e.g., 'tomorrow @ 2pm' or 'next friday'")
        self.when_input.setStyleSheet("QLineEdit { color: #071622; background: #ffffff; }")
        # if caller provided a default when-text (e.g., column date), prefill it
        if getattr(self, 'default_when_text', None):
            try:
                self.when_input.setText(self.default_when_text)
            except Exception:
                pass
        layout.addWidget(self.when_input)
        
        # Category
        layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(["Personal", "Work", "School"])
        self.category_combo.setStyleSheet("QComboBox { color: #071622; background: #ffffff; }")
        layout.addWidget(self.category_combo)

        # If default category provided, select it
        if self.default_category:
            idx = self.category_combo.findText(self.default_category)
            if idx >= 0:
                self.category_combo.setCurrentIndex(idx)

        # Recurrence
        layout.addWidget(QLabel("Recurrence:"))
        self.recurrence_combo = QComboBox()
        self.recurrence_combo.addItems(["None", "Daily", "Weekdays", "Weekly (same weekday)"])
        self.recurrence_combo.setStyleSheet("QComboBox { color: #071622; background: #ffffff; }")
        layout.addWidget(self.recurrence_combo)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        create_btn = QPushButton("Create")
        create_btn.setObjectName('CreateBtn')
        # prominent confirm button: frutiger-aero blue with white text
        create_btn.setStyleSheet("QPushButton#CreateBtn { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #1e90ff, stop:1 #0066cc); color: white; border-radius: 8px; padding: 6px 14px; font-weight: 700; }")
        create_btn.clicked.connect(self.create_task)
        button_layout.addWidget(create_btn)
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setObjectName('CancelBtn')
        cancel_btn.setStyleSheet("QPushButton#CancelBtn { background: #ffffff; color: #08314b; border: 1px solid #d0e6fb; border-radius:8px; padding:6px 12px; }")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        
        layout.addLayout(button_layout)
    
    def create_task(self):
        """Validate and create task."""
        try:
            title = self.title_input.text().strip()
            if not title:
                QMessageBox.warning(self, "Error", "Please enter a task title.")
                return
            
            when_str = self.when_input.text().strip()
            when = parse_datetime(when_str) if when_str else None
            category = self.category_combo.currentText()
            rec_sel = self.recurrence_combo.currentText()
            recurrence = None if rec_sel == "None" else (
                "daily" if rec_sel == "Daily" else ("weekdays" if rec_sel == "Weekdays" else "weekly")
            )
            
            self.result_task = Task(
                id=str(datetime.now().timestamp()),
                title=title,
                when=when,
                category=category,
                recurrence=recurrence,
                done=False,
                created_at=datetime.now()
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to create task: {str(e)}")
            print(f"DEBUG: {e}")


class WorkWeekGUI(QMainWindow):
    """Main window for the WorkWeek scheduler."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkWeek — 14-Day Scheduler")
        self.setGeometry(100, 100, 1400, 800)
        
        self.tasks: List[Task] = []
        self.day_columns: List[DayColumn] = []
        # guard to prevent opening multiple new-task dialogs from rapid clicks
        self._creating_task = False
        
        # timer to debounce saves (prevents frequent file I/O on UI thread)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.timeout.connect(self._perform_save)

        self.setup_ui()
        self.load_and_display_tasks()
        # keep one subtle shadow on the main window only
        FrutigerAeroStyle.apply_shadow(self)
    
    def setup_ui(self):
        """Create the main window layout (Kanban-style by category)."""
        # Menu bar
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")
        new_action = file_menu.addAction("&New Task")
        new_action.setShortcut("Ctrl+N")
        new_action.triggered.connect(self.new_task_dialog)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("&Quit")
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.quit_app)

        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Header: title + single New Task button (compact and readable)
        header_row = QHBoxLayout()
        title = QLabel("14-Day Planner")
        title.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        header_row.addWidget(title)
        header_row.addStretch()
        new_task_btn = QPushButton("New Task")
        new_task_btn.setFixedHeight(34)
        new_task_btn.clicked.connect(self.new_task_dialog)
        header_row.addWidget(new_task_btn)
        main_layout.addLayout(header_row)

        # Main board area (calendar-style grid: horizontal day columns)
        board_scroll = QScrollArea()
        board_scroll.setWidgetResizable(True)
        board_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        board_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        board_scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        board_container = QWidget()
        # horizontal columns (calendar-like) — will contain DayColumn widgets
        self.board_layout = QHBoxLayout(board_container)
        self.board_layout.setSpacing(12)
        self.board_layout.setContentsMargins(8, 8, 8, 8)

        board_scroll.setWidget(board_container)
        main_layout.addWidget(board_scroll)

        # Filter / search bar
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(0, 6, 0, 6)
        filter_label = QLabel("Filter:")
        filter_row.addWidget(filter_label)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All", "Done", "Not Done"])
        filter_row.addWidget(self.status_filter)
        filter_row.addStretch()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search tasks...")
        self.search_input.setFixedWidth(300)
        filter_row.addWidget(self.search_input)
        main_layout.insertLayout(2, filter_row)

        # No category columns — we use stacked day sections for readability.
        # Individual day widgets are created when loading tasks.

        # wire up filters
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        self.search_input.textChanged.connect(self.apply_filters)

        # Status bar
        self.statusBar().showMessage("Ready")
    
    def load_and_display_tasks(self):
        """Load tasks from disk and populate the Kanban board by category."""
        # Load all tasks and populate 14-day columns
        self.tasks = load_tasks()

        # clear existing columns/widgets
        for col in getattr(self, 'day_columns', []):
            col.deleteLater()
        self.day_columns = []
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        today = datetime.now()

        # Unscheduled column
        unscheduled_col = DayColumn(None)
        unscheduled_col.task_changed.connect(self.on_task_changed)
        self.day_columns.append(unscheduled_col)
        self.board_layout.addWidget(unscheduled_col)

        # 14 day columns
        for i in range(14):
            date = today + timedelta(days=i)
            col = DayColumn(date)
            col.task_changed.connect(self.on_task_changed)
            self.day_columns.append(col)
            self.board_layout.addWidget(col)

        # Expand recurring tasks into occurrences for the 14-day window
        start_dt = today
        end_dt = today + timedelta(days=13)
        occurrences = _occurrences_between(self.tasks, start_dt, end_dt)

        # Place unscheduled non-recurring tasks into unscheduled column
        for task in self.tasks:
            if task.when is None and not task.recurrence:
                self.day_columns[0].add_task(task)

        # Place occurrences into the appropriate day column
        for occ in occurrences:
            occ_date = occ.when.date()
            for i, col in enumerate(self.day_columns[1:], start=1):
                if col.date and col.date.date() == occ_date:
                    col.add_task(occ)
                    break
            else:
                self.day_columns[0].add_task(occ)

    def quick_new_task(self, category: str):
        """Open NewTaskDialog preselected to category and add task if created."""
        if self._creating_task:
            return
        self._creating_task = True
        try:
            dialog = NewTaskDialog(self, default_category=category)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
                self.tasks.append(dialog.result_task)
                save_tasks(self.tasks)
                self.load_and_display_tasks()
                self.apply_filters()
                self.statusBar().showMessage(f"Created: {dialog.result_task.title}")
        finally:
            self._creating_task = False

    def new_task_for_date(self, date: datetime, default_when_text: Optional[str] = None):
        """Open NewTaskDialog prefilled for a specific date (used by DayColumn).

        `default_when_text` should be a human-friendly string like 'Sunday 11/23'.
        """
        if self._creating_task:
            return
        self._creating_task = True
        try:
            dialog = NewTaskDialog(self, default_category=None, default_when_text=default_when_text)
            if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
                self.tasks.append(dialog.result_task)
                save_tasks(self.tasks)
                self.load_and_display_tasks()
                self.apply_filters()
                self.statusBar().showMessage(f"Created: {dialog.result_task.title}")
        finally:
            self._creating_task = False

    def apply_filters(self):
        """Show/hide task widgets based on status filter and search text."""
        status = self.status_filter.currentText()
        text = self.search_input.text().lower().strip()
        for col in getattr(self, 'day_columns', []):
            # iterate all widgets in all-day and hour rows to apply visibility
            # all-day
            if hasattr(col, 'all_day_layout'):
                for i in range(col.all_day_layout.count()):
                    widget = col.all_day_layout.itemAt(i).widget()
                    if not widget or not isinstance(widget, TaskWidget):
                        continue
                    matches_search = (not text) or (text in (widget.task.title or "").lower()) or (widget.task.category is not None and text in widget.task.category.lower())
                    matches_search = bool(matches_search)
                    if status == "Done" and not widget.task.done:
                        status_ok = False
                    elif status == "Not Done" and widget.task.done:
                        status_ok = False
                    else:
                        status_ok = True
                    widget.setVisible(matches_search and status_ok)
            # hour rows
            if hasattr(col, 'hour_rows'):
                for row in col.hour_rows:
                    l = row.layout()
                    if not l:
                        continue
                    for i in range(l.count()):
                            widget = l.itemAt(i).widget()
                            if not widget or not isinstance(widget, TaskWidget):
                                continue
                            matches_search = (not text) or (text in (widget.task.title or "").lower()) or (widget.task.category is not None and text in widget.task.category.lower())
                            matches_search = bool(matches_search)
                            if status == "Done" and not widget.task.done:
                                status_ok = False
                            elif status == "Not Done" and widget.task.done:
                                status_ok = False
                            else:
                                status_ok = True
                            widget.setVisible(matches_search and status_ok)
    
    def on_task_changed(self):
        """Refresh display and save tasks when any task changes."""
        # Debounce saves and avoid blocking UI: restart timer on each change
        try:
            if self._save_timer.isActive():
                self._save_timer.stop()
            # start timer to save after 800ms idle
            self._save_timer.start(800)
        except Exception as e:
            print(f"ERROR scheduling save: {e}")
            self.statusBar().showMessage(f"Error scheduling save: {str(e)}")

    def _perform_save(self):
        """Collect current tasks from visible widgets and persist to disk."""
        try:
            all_tasks = []
            for col in getattr(self, 'day_columns', []):
                # collect from all-day
                if hasattr(col, 'all_day_layout'):
                    for i in range(col.all_day_layout.count()):
                        w = col.all_day_layout.itemAt(i).widget()
                        if isinstance(w, TaskWidget):
                            all_tasks.append(w.task)
                # collect from hour rows
                if hasattr(col, 'hour_rows'):
                    for row in col.hour_rows:
                        l = row.layout()
                        if not l:
                            continue
                        for i in range(l.count()):
                            w = l.itemAt(i).widget()
                            if isinstance(w, TaskWidget):
                                all_tasks.append(w.task)

            self.tasks = all_tasks
            save_tasks(self.tasks)
            self.statusBar().showMessage(f"Saved {len(self.tasks)} task(s)")
        except Exception as e:
            print(f"ERROR in _perform_save: {e}")
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def new_task_dialog(self):
        """Open new task dialog and add task to board."""
        dialog = NewTaskDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
            # append to storage and refresh
            self.tasks.append(dialog.result_task)
            save_tasks(self.tasks)
            self.load_and_display_tasks()
            self.statusBar().showMessage(f"Created: {dialog.result_task.title}")

    def quit_app(self):
        """Save and quit."""
        save_tasks(self.tasks)
        self.close()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Set global font for humanist look
    font = QFont("Segoe UI", 11)
    # Fallbacks for macOS
    if not font.exactMatch():
        font = QFont("Arial Rounded MT Bold", 11)
    if not font.exactMatch():
        font = QFont("Arial", 11)
    app.setFont(font)
    app.setStyleSheet(FrutigerAeroStyle.get_stylesheet())

    window = WorkWeekGUI()
    window.show()
    sys.exit(app.exec())
