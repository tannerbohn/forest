# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Forest is a minimal tree-based note-taking interface built with Textual (Python TUI framework). It allows users to create, edit, and navigate hierarchical notes stored as indented text files.

## Setup and Development

### Installation
```bash
python3 -m pip install -r requirements.txt
```

### Configuration
Forest uses `config.json` in the project root for settings:
- `sound_effects_enabled` (boolean): Enable/disable sound effects on startup
- `default_theme` (string): Theme name (e.g., "forest", "dracula")
- `log_level` (string): Logging level ("DEBUG", "INFO", "WARNING", "ERROR")
- `undo_depth` (integer): Max number of undo steps (default: 50)
- `auto_save` (boolean): Enable/disable periodic auto-save (default: true)
- `auto_save_interval` (integer): Seconds between auto-save checks (default: 5)
- `margin_side` (string, "left" or "right"): Side of the screen where the tree margin and InfoSidebar are placed (default: "right")
- `margin_width` (integer): Cells reserved on `margin_side` for the tree margin and sidebar width. Dropped if it would shrink the tree below a small internal minimum; the sidebar still overlays at this width (default: 30)
- `scroll_margin` (integer): Minimum lines kept between the cursor and the top/bottom of the tree viewport before scrolling. `0` = scroll only at the edge; large values approximate centering. Clamped to at most half the viewport (default: 5)
- `doodle_pane_visible` (boolean): Whether the doodle pane is shown at startup (default: true)

If `config.json` is missing, Forest uses defaults (sounds enabled, "forest" theme, INFO logging). Copy `config.json.example` to `config.json` to customize settings.

### Running the Application
```bash
python3 src/forest.py trees/intro.txt
```

To create a new tree:
```bash
touch trees/my_new_tree.txt
python3 src/forest.py trees/my_new_tree.txt
```

### Dependencies
- `textual`: TUI framework
- `pytimeparse`: Time duration parsing
- `playsound3`: Sound effects playback
- `watchdog`: File system monitoring (currently unused in code)

## Architecture

### Core Data Model

**Node (node.py)**: The fundamental data structure representing a single note
- Hierarchical tree structure with parent/children relationships
- Each node has: text content, depth, collapse state, creation time
- Supports hashtags for special behaviors (#DONE, #HL1-3, #T-, etc.)
- Supports value extraction ($variable=value syntax) for aggregation functions

**NoteTree (note_tree.py)**: Manages the entire tree and persistence
- Loads/saves notes from tab-indented text files with inline metadata
- Each line format: `<tabs><prefix> <text> @{YYYY-MM-DD[,b#][,x]}` where `-`/`+` prefix indicates expanded/collapsed, and `@{...}` suffix stores creation date, optional bookmark slot (`b0`-`b9`), and optional context marker (`x`)
- Maintains bookmarks (0-9 keys) and journal entries
- Context management: The "context node" determines which branch is currently visible

**NoteTreeWidget (note_tree_widget.py)**: Textual Tree widget for display
- Renders NoteTree as an interactive TUI
- Handles text wrapping for long notes
- Custom line rendering with age indicators, bookmarks, and styling
- Cursor navigation and view management

**Config (config.py)**: Application configuration management
- Loads settings from `config.json` in project root
- Falls back to defaults if config file missing
- Manages: sound effects, theme, log level

**Widgets (widgets/)**: Extracted UI components, each with own `DEFAULT_CSS`
- **StatusBar**: Reactive status line (context path, save state, timer, search progress)
- **InfoSidebar**: DataTable-based side panel (bookmarks, copied notes, archived, perpetual journal, search results, help)
- **MultiPurposeSuggester**: Auto-completion suggester for command and edit modes (in `suggesters.py`)

**CopiedList (copied_list.py)**: Non-widget helper attached to `ForestApp` as `app.copied_list`. Manages the copied node list (toggle/prune/rotate/cycle_target/jump_to_next) backed by `note_tree.copied_nodes`. The list is rendered as a section inside the InfoSidebar's bookmarks view.

**SearchState (search_state.py)**: Dataclass encapsulating search mode state (matches, index, query, pre-search position)

### Application Flow

1. **Startup**: Config loaded, then ForestApp (forest.py) loads a note file path
2. **Loading**: NoteTree parses the text file (metadata is inline)
3. **Rendering**: NoteTreeWidget builds Textual tree widgets from nodes
4. **Interaction**: User navigates/edits via keyboard bindings
5. **Saving**: Modified tree is written back to text file with inline metadata

### Key Concepts

**Context Node**: The currently focused branch of the tree. Zooming in/out changes the context node, affecting which notes are visible.

**Multiline Rendering**: Long notes wrap across multiple lines. First line widget gets arrow, other lines are indented. Tracked via `_first_widget_of_multiline` and `_last_widget_of_multiline`.

**Node State**: Persisted inline in each line's `@{...}` suffix:
- Collapsed/expanded state (line prefix `+`/`-`)
- Bookmark assignments (`b0`-`b9`)
- Context node (`x` flag)
- Creation date (`YYYY-MM-DD`)

## Special Features

### Hashtags
- `#DONE`: Marks task complete, dims in UI
- `#HL1`, `#HL2`, `#HL3`: Color highlighting
- `#T-<duration>`: Expiring notes (e.g., #T-7d)
- `#sum`, `#max`, `#min`, `#avg`: Aggregate child values

### Value System
- Use `$variable=value` syntax in notes
- Use `$variable_inc=value` or `$variable_dec=value` to auto-increment/decrement on toggle done
- Aggregation hashtags compute over child node values

### Bookmarks
- 0-9 keys jump to bookmarked notes
- Command mode `:b` or `:bookmark` toggles bookmark on cursor
- Least recently used bookmark gets replaced when all 10 slots full
- Displayed with 💠 icon in left margin

### Journal
- Command `:j+ <text>` adds timestamped journal entry
- Auto-creates hierarchy: Journal → Year → Month → Entry
- Entries formatted as `[YYYY-MM-DD HH:MM] text`

### Search
- `:?<query>`: Search within current context
- `:?*<query>` or `:??<query>`: Global search
- `:?` (empty query): Find notes similar to the cursor node
- Uses trigram similarity matching (utils.py)
- Path matching with `>` separator (e.g., `?Parent>Child`)
- Up/down arrows navigate results, Enter accepts, Escape cancels

### Subtrees
- Command `:insert <name>` inserts predefined template
- Templates defined in subtrees.py (BRAINSTORM, NOTICE, VALUES, etc.)

### Command Mode
- Press `:` to enter command mode (up/down arrows for command history)
- `j+ <text>`: Add journal entry
- `?<query>` or `?*<query>` / `??<query>`: Search (local/global)
- `b` or `bookmark`: Toggle bookmark
- `help`: Show help panel
- `timer <duration>`: Start timer (e.g., `5m`, `25m 3x`)
- `timer cancel`: Cancel a running timer
- `run`: Execute shell command (if note starts with `!`) or follow `[[path]]` references
- `run <index>`: Follow the Nth `[[path]]` reference in the current note
- `insert <subtree>`: Insert template
- `collapse`: Collapse all nodes in current context
- `random` / `random*`: Jump to a random note (local/global)
- `sn` / `sn*`: Open sticky notes board showing highlighted notes (local/global)
- `sn <filter>` / `sn* <filter>`: Sticky notes filtered by `#HL1`/`#HL2`/`#HL3` or regex
- `snr`: Recover/reopen the last sticky notes board

### Input Substitutions
- `{NOW}`: Replaced with current timestamp `[YYYY-MM-DD HH:MM]`

### Sound Effects
- Audio feedback for opening a file and timer events

## File Organization

```
src/
  forest.py           - Main app (ForestApp class, keybindings, command dispatch)
  note_tree.py        - NoteTree class (data model and persistence)
  node.py             - Node class (single note logic)
  note_tree_widget.py - NoteTreeWidget class (UI rendering)
  search_state.py     - SearchState dataclass (search mode state)
  sound_effects.py    - SoundEffects class (audio feedback system)
  timer.py            - Timer class (countdown timer with repeats)
  config.py           - Config class (settings management)
  sticky_notes.py     - StickyNotesScreen (board view for filtered notes)
  utils.py            - Helper functions (trigram search, substitutions)
  subtrees.py         - Predefined note templates
  themes.py           - Color theme definitions
  copied_list.py      - CopiedList helper (copy/paste/cycle logic; renders in sidebar)
  widgets/
    status_bar.py     - StatusBar (context path, save indicator, timer)
    info_sidebar.py   - InfoSidebar (bookmarks, copied, archived, journal, search, help)
    suggesters.py     - MultiPurposeSuggester (command/edit auto-completion)

trees/
  intro.txt           - Example/intro tree

config.json           - User configuration (optional, uses defaults if missing)
config.json.example   - Example configuration file (template)
```

## Key Bindings

### Main bindings (defined in ForestApp.BINDINGS)
- `e` or `backspace`: Edit current note
- `:`: Enter command mode
- `` ` `` (backtick): Cycle side panel (bookmarks/journal views)

### Tree navigation (defined in NoteTreeWidget.BINDINGS)
- `s`: Save
- `left`: Zoom out (go to parent context)
- `right`: Zoom in (make current note the context)
- `space`: Toggle collapse/expand
- `h`: Cycle highlight (#HL1 → #HL2 → #HL3 → none)
- `x`: Toggle done (#DONE)
- `X`: Toggle hiding #DONE nodes
- `tab`: Indent (make child of previous sibling)
- `shift+tab`: Deindent (move up in hierarchy)
- `delete`: Delete node (collapses to parent if collapsed, else single)
- `u`: Move note up
- `d`: Move note down
- `c`: Cut node
- `v`: Paste node
- `enter`: Add new note
- `0-9`: Jump to bookmark
- `z`: Undo
- `Z`: Redo

## Logging

Application logs to `log.txt` in the project root. Use `logging.info()`, `logging.error()`, etc. for debugging.

## Theme

Custom theme defined in `forest_theme` (forest.py) with warm brown/orange color palette. Theme variables include custom colors for highlights (HL1-3), age gradients, and arrows.
