Phase 1: Core Functionality (The Must-Haves)

- [ X ] 1.1 Project Setup: Install typer, rich, and pydantic.

- [ X ] 1.2 Data Persistence: Define the Task model and create functions to load/save tasks to schedule.json.

- [ ] 1.3 Fast Add Command: Implement the workweek add command with natural date parsing.

- [ ] 1.4 14-Day View: Implement the workweek view command to filter and display the current 14 days in a simple list.

Phase 2: User Interface (The Clean Look)

- [ ] 2.1 TUI Integration: Set up the Terminal User Interface framework.

- [ ] 2.2 14-Day Layout: Design the TUI screen to show the 14 days clearly, one column for each day.

- [ ] 2.3 Simple Interaction: Add keyboard controls (up/down/enter) to select, mark as done, or delete tasks directly in the TUI.

Phase 3: Polish & Robustness (The Finish)

- [ ] 3.1 Recurring Tasks: Add logic for tasks that repeat daily or weekly.

- [ ] 3.2 Error Handling: Add checks for bad user input or a corrupted JSON file.

- [ ] 3.3 Color Coding: Use colors (e.g., Work = Blue, School = Green) for easy category viewing.

- [ ] 3.4 Packaging: Prepare the application for easy installation via pip (create pyproject.toml).
