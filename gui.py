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
    QComboBox, QMessageBox, QMenu, QFrame
)
from PyQt6.QtCore import Qt, QDate, QDateTime, QSize, pyqtSignal, QRect
from PyQt6.QtGui import QColor, QFont, QAction, QIcon, QPalette

from workweek import load_tasks, save_tasks, Task, parse_datetime, _occurrences_between


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
    
    def setup_ui(self):
        """Create the task display with checkbox and title."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        
        # Checkbox (done/undone)
        self.check_btn = QPushButton("✓" if self.task.done else "○")
        self.check_btn.setMaximumWidth(30)
        self.check_btn.clicked.connect(self.toggle_done)
        layout.addWidget(self.check_btn)
        
        # Title label
        self.title_label = QLabel(self.task.title)
        self.title_label.setWordWrap(True)
        if self.task.done:
            font = self.title_label.font()
            font.setStrikeOut(True)
            self.title_label.setFont(font)
        layout.addWidget(self.title_label)
        
        # Apply category color
        self.setStyleSheet(self._get_color_style())
        self.setFrameStyle(QFrame.Shape.StyledPanel | QFrame.Shadow.Raised)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
    
    def _get_color_style(self) -> str:
        """Return stylesheet for category color."""
        category = self.task.category or "Personal"
        colors = {
            "Work": "#0066CC",      # Blue
            "School": "#00AA00",    # Green
            "Personal": "#CC00CC"   # Magenta
        }
        bg_color = colors.get(category, "#CCCCCC")
        return f"""
            QFrame {{
                background-color: {bg_color};
                border-radius: 4px;
                padding: 4px;
                color: white;
                border: 1px solid #999;
            }}
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.3);
                border: none;
                border-radius: 3px;
                color: white;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 255, 255, 0.5);
            }}
            QLabel {{
                color: white;
                font-weight: 500;
            }}
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
        
        delete_action = menu.addAction("Delete")
        delete_action.triggered.connect(self.delete_task)
        
        menu.exec(event.globalPos())
    
    def mouseDoubleClickEvent(self, event):
        """Double-click to edit via $EDITOR."""
        self.edit_task()
    
    def edit_task(self):
        """Open task in $EDITOR for editing."""
        task_dict = {
            "title": self.task.title,
            "when": self.task.when.isoformat() if self.task.when else None,
            "category": self.task.category
        }
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(task_dict, f, indent=2)
            temp_path = f.name
        
        try:
            editor = os.environ.get('EDITOR', 'vi')
            subprocess.run([editor, temp_path], check=True)
            
            with open(temp_path, 'r') as f:
                updated = json.load(f)
            
            self.task.title = updated.get('title', self.task.title)
            self.task.category = updated.get('category', self.task.category)
            
            if updated.get('when'):
                self.task.when = parse_datetime(updated['when']) or self.task.when
            
            self.title_label.setText(self.task.title)
            self.setStyleSheet(self._get_color_style())
            self.task_changed.emit()
        except Exception as e:
            print(f"Edit failed: {e}")
        finally:
            os.unlink(temp_path)
    
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
        layout.setSpacing(4)
        
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
        header.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        layout.addWidget(header)
        
        # Scrollable task container
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #F5F5F5; }")
        
        task_container = QWidget()
        self.task_layout = QVBoxLayout(task_container)
        self.task_layout.setSpacing(6)
        
        scroll.setWidget(task_container)
        layout.addWidget(scroll)
        
        # Style column
        self.setStyleSheet("""
            DayColumn {
                background-color: #F5F5F5;
                border: 1px solid #DDD;
                border-radius: 4px;
            }
        """)
    
    def add_task(self, task: Task):
        """Add a task widget to this column."""
        self.tasks.append(task)
        task_widget = TaskWidget(task)
        task_widget.task_changed.connect(self._on_task_changed)
        self.task_layout.addWidget(task_widget)
    
    def clear_tasks(self):
        """Remove all task widgets."""
        while self.task_layout.count():
            self.task_layout.takeAt(0).widget().deleteLater()
        self.tasks.clear()
    
    def _on_task_changed(self):
        """Propagate task change to parent."""
        self.task_changed.emit()


class NewTaskDialog(QDialog):
    """Dialog to create a new task."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New Task")
        self.setGeometry(100, 100, 400, 200)
        self.result_task = None
        self.setup_ui()
    
    def setup_ui(self):
        """Create form widgets."""
        layout = QVBoxLayout(self)
        
        # Title
        layout.addWidget(QLabel("Title:"))
        self.title_input = QLineEdit()
        layout.addWidget(self.title_input)
        
        # When (optional)
        layout.addWidget(QLabel("When (optional):"))
        self.when_input = QLineEdit()
        self.when_input.setPlaceholderText("e.g., 'tomorrow @ 2pm' or 'next friday'")
        layout.addWidget(self.when_input)
        
        # Category
        layout.addWidget(QLabel("Category:"))
        self.category_combo = QComboBox()
        self.category_combo.addItems(["Personal", "Work", "School"])
        layout.addWidget(self.category_combo)

        # Recurrence
        layout.addWidget(QLabel("Recurrence:"))
        self.recurrence_combo = QComboBox()
        self.recurrence_combo.addItems(["None", "Daily", "Weekdays", "Weekly (same weekday)"])
        layout.addWidget(self.recurrence_combo)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        create_btn = QPushButton("Create")
        create_btn.clicked.connect(self.create_task)
        button_layout.addWidget(create_btn)
        
        cancel_btn = QPushButton("Cancel")
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
        
        self.setup_ui()
        self.load_and_display_tasks()
    
    def setup_ui(self):
        """Create the main window layout."""
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
        
        # Main grid
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        
        # Title
        title = QLabel("14-Day Scheduler")
        title.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        main_layout.addWidget(title)
        
        # Scrollable day columns
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")
        
        grid_container = QWidget()
        self.grid_layout = QHBoxLayout(grid_container)
        self.grid_layout.setSpacing(8)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
        
        scroll.setWidget(grid_container)
        main_layout.addWidget(scroll)
        
        # Status bar
        self.statusBar().showMessage("Ready")
    
    def load_and_display_tasks(self):
        """Load tasks from disk and populate the grid."""
        # Load all tasks
        self.tasks = load_tasks()
        
        # Clear existing columns
        for col in self.day_columns:
            col.deleteLater()
        self.day_columns.clear()
        while self.grid_layout.count():
            self.grid_layout.takeAt(0).widget().deleteLater()
        
        # Create columns for next 14 days
        today = datetime.now()
        
        # Unscheduled column
        unscheduled_col = DayColumn(None)
        unscheduled_col.task_changed.connect(self.on_task_changed)
        self.day_columns.append(unscheduled_col)
        self.grid_layout.addWidget(unscheduled_col)
        
        for i in range(14):
            date = today + timedelta(days=i)
            col = DayColumn(date)
            col.task_changed.connect(self.on_task_changed)
            self.day_columns.append(col)
            self.grid_layout.addWidget(col)
        
        # Distribute tasks — expand recurring tasks into occurrences for the 14-day window
        start_dt = today
        end_dt = today + timedelta(days=13)
        occurrences = _occurrences_between(self.tasks, start_dt, end_dt)

        # Add unscheduled (non-recurring) tasks
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
    
    def on_task_changed(self):
        """Refresh display and save tasks when any task changes."""
        try:
            # Collect all tasks from columns
            all_tasks = []
            for col in self.day_columns:
                for i in range(col.task_layout.count()):
                    widget = col.task_layout.itemAt(i).widget()
                    if isinstance(widget, TaskWidget):
                        all_tasks.append(widget.task)
            
            self.tasks = all_tasks
            save_tasks(self.tasks)
            self.statusBar().showMessage(f"Saved {len(self.tasks)} task(s)")
        except Exception as e:
            print(f"ERROR in on_task_changed: {e}")
            self.statusBar().showMessage(f"Error: {str(e)}")
    
    def new_task_dialog(self):
        """Open new task dialog."""
        dialog = NewTaskDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_task:
            self.tasks.append(dialog.result_task)
            save_tasks(self.tasks)
            self.load_and_display_tasks()
            self.statusBar().showMessage(f"Created: {dialog.result_task.title}")
    
    def quit_app(self):
        """Save and quit."""
        save_tasks(self.tasks)
        self.close()


if __name__ == "__main__":
    try:
        app = QApplication(sys.argv)
        window = WorkWeekGUI()
        window.show()
        sys.exit(app.exec())
    except Exception as e:
        print(f"FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
