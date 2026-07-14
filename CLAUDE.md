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
- `default_theme` (string): Theme name (e.g., "forest", "dracula")
- `log_level` (string): Logging level ("DEBUG", "INFO", "WARNING", "ERROR")
- `undo_depth` (integer): Max number of undo steps (default: 50)
- `auto_save` (boolean): Enable/disable periodic auto-save (default: true)
- `auto_save_interval` (integer): Seconds between auto-save checks (default: 5)
- `margin_width` (integer): Cells reserved on the right for the tree margin and InfoSidebar width. Dropped if it would shrink the tree below a small internal minimum; the sidebar still overlays at this width (default: 30). The InfoSidebar is always on the right and the doodle pane always on the left; both margins are reserved permanently (the panes toggle visibility within the reserved strip) and are only dropped when they would crowd the tree.
- `scroll_margin` (integer): Minimum lines kept between the cursor and the top/bottom of the tree viewport before scrolling. `0` = scroll only at the edge; large values approximate centering. Clamped to at most half the viewport (default: 5)

If `config.json` is missing, Forest uses defaults ("forest" theme, INFO logging). Copy `config.json.example` to `config.json` to customize settings.

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
- `playsound3`: Timer sound playback
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

**NoteTreeWidget (note_tree_widget.py)**: Virtualized display widget (Textual `ScrollView` + Line API)
- Derives a flat list of `VisualRow`s (one per screen row, wrapping resolved up front) from `note_tree.visible_node_list`; paints only viewport rows via `render_line`
- Per-node wrap results cached (`_wrap_cache`); styling-only actions (highlight/done/copy/bookmark) repaint in place via `_restyle_node` instead of rebuilding the row list
- Custom line rendering with age indicators, bookmarks, and styling
- Cursor navigation and view management

**Config (config.py)**: Application configuration management
- Loads settings from `config.json` in project root
- Falls back to defaults if config file missing
- Manages: theme, log level

**Widgets (widgets/)**: Extracted UI components, each with own `DEFAULT_CSS`
- **StatusBar**: Reactive status line (context path, save state, timer, search progress)
- **InfoSidebar**: DataTable-based side panel (bookmarks, copied notes, expiring notes, archived, perpetual journal, search results, help)
- **MultiPurposeSuggester**: Auto-completion suggester for command and edit modes (in `suggesters.py`)

**CopiedList (copied_list.py)**: Non-widget helper attached to `ForestApp` as `app.copied_list`. Manages the copied node list (toggle/prune/rotate/cycle_target/jump_to_next) backed by `note_tree.copied_nodes`. The list is rendered as a section inside the InfoSidebar's bookmarks view.

**SearchState (search_state.py)**: Dataclass encapsulating search mode state (matches, index, query, pre-search position)

### Application Flow

1. **Startup**: Config loaded, then ForestApp (forest.py) loads a note file path
2. **Loading**: NoteTree parses the text file (metadata is inline)
3. **Rendering**: NoteTreeWidget derives a flat line-list from the visible nodes and paints viewport rows
4. **Interaction**: User navigates/edits via keyboard bindings
5. **Saving**: Modified tree is written back to text file with inline metadata

### Key Concepts

**Context Node**: The currently focused branch of the tree. Zooming in/out changes the context node, affecting which notes are visible.

**Multiline Rendering**: Long notes wrap across multiple screen rows. Each wrap segment is its own `VisualRow` (`seg_index`/`seg_count`); the first segment bears the arrow, later segments are indented to align under the text.

**Node State**: Persisted inline in each line's `@{...}` suffix:
- Collapsed/expanded state (line prefix `+`/`-`)
- Bookmark assignments (`b0`-`b9`)
- Context node (`x` flag)
- Creation date (`YYYY-MM-DD`)

## Special Features

### Hashtags
- `#DONE`: Marks task complete, dims in UI
- `#HL1`, `#HL2`, `#HL3`: Color highlighting
- `#T-<duration>`: Expiring notes (e.g., #T-7d). `#T-*<duration>` auto-renews (recurring). See Expiring Notes below.
- `#sum`, `#max`, `#min`, `#avg`: Aggregate child values

### Expiring Notes
- Tag a note `#T-<duration>` (e.g. `#T-7d`, `#T-30m`, `#T-2mo`, `#T-1y`) to give it a countdown. Durations use `pytimeparse`, extended with `mo` (months) and `y` (years) via `extended_parse` (node.py).
- On first parse the tag is rewritten to `#T-<duration>@<expiry-iso>` (e.g. `#T-7d@2026-07-14T15:30:00`), keeping both the original duration (for reset) and the computed absolute expiry (stable across reloads). The `#T-...` token is hidden from the displayed note text. Legacy `#T-<expiry-iso>` tags (no duration) still display but can't be reset.
- A note that owns a timer shows a color-coded **`T`** in the left gutter (`#HL2` while counting down, `#HL3`/red when expired) and an inline readout: `⏳2d` while counting down, `⌛3d ago` once expired. Expired notes are **not deleted** — the whole line is dimmed/reddened so it's obvious. The gutter `T` yields to the bookmark/copied glyph when both apply; the inline readout still conveys expiry. Expiry is inherited by descendants for logic, but the gutter/readout decorate only the tagged note.
- Expiry is checked on a frequent tick (`_tick_expiry`, every 10s) and a **notification fires once when a note expires** during a session (with the same sound cue as `:timer`, via `play_sound_effect("timer")`; recurring notes show a `↺` in the notification). Notes already expired at load are pre-marked so opening a file doesn't spam stale notifications; renewing a note re-arms it. Expiry checking is global: `NoteTree.timer_nodes` is the registry of all `#T-` notes; `check_expirations()` iterates it (skipping entries that are no longer live via `_timer_node_live`) and returns the notes that crossed expiry since the last check. The frequent tick only walks this (small) registry — never the whole tree. The registry itself is a whole-tree walk, so it's rebuilt on a **slower 60s cadence** (`_refresh_timer_registry` → `refresh_timer_nodes()`, which also refreshes the sidebar labels); it's also built once up front in `on_mount` so the first check has fresh data. A newly added `#T-` note therefore enters the registry within ~60s.
- The bookmarks side panel (`` ` `` to cycle) lists all timer notes in an **Expiring** section below the Copied Stack, sorted soonest-expiry first; expired entries render dim red, still-counting entries render plain (`_build_expiring_rows` in `widgets/info_sidebar.py`).
- Press `r` on a note to **renew** it — restart the countdown for its original duration. When the cursor is on an expired note, a `[r]enew` hint appears in the status bar, just left of `[s]ave`. Renew is undoable (`z`).

### Recurring (auto-renewing) Expiry & Commands on Expiry
- Add a `*` right after the prefix — `#T-*<duration>` (e.g. `#T-*1d`) — to make a timer **auto-renew**: when it expires, `check_expirations()` re-arms it for another cycle instead of leaving it expired. The marker sits inside the `#T-` token (so every `startswith("#T-")` check still applies and it's stripped from display) and is preserved across migration and renew. Recurring timers show a `↺` in the inline readout (e.g. `⏳2d ↺`). Auto-renew sets `has_unsaved_operations` but is **not** pushed to the undo stack (unlike manual `r`).
- When an **expiry note is also a command note** (text starts with `!`), the command runs automatically the moment the note expires — the run happens in `_tick_expiry` for each node returned by `check_expirations()`. Combined with recurrence this is cron-like: `!backup.sh #T-*1d` runs `backup.sh` daily; `!subl notes.py #T-7d` is a one-shot deferred command. `run_command()` strips Forest control tokens (`#T-...`, `#DONE`, `#HL*`) so they aren't passed to the shell. Commands that lapsed while the app was closed do **not** backfill on open (already-expired-at-load notes are pre-marked); recurring ones still re-arm for the next cycle.

### Value System
- Use `$variable=value` syntax in notes
- Use `$variable_inc=value` or `$variable_dec=value` to auto-increment/decrement on toggle done
- Aggregation hashtags compute over child node values

### Bookmarks
- 0-9 keys jump to bookmarked notes
- Command mode `:b` or `:bookmark` toggles bookmark on cursor
- Least recently used bookmark gets replaced when all 10 slots full
- Displayed with 💠 icon in left margin

### Context History
- Browser-style back/forward over context changes. `alt+left` = back, `alt+right` = forward.
- Implemented by `ContextHistory` (pure data helper in `context_history.py`): a flat list of `(context_node, cursor_node)` entries plus an index, owned by `NoteTreeWidget` as `self.context_history`. In-memory only (not persisted), seeded in `ForestApp.on_mount`.
- `NoteTreeWidget.update_location(context_node, line_node=None, record=True)` is the **single navigation primitive** — the only method that changes the context — so all history logic lives there and nowhere else: it calls `context_history.mark_leaving(...)` *before* the move (refreshing the current entry's cursor to where it actually sits, so back restores it) and `context_history.record(...)` *after* (appending the destination). `line_node=None` places the cursor at the top of the new context. Every navigation routes through it: `action_zoom_in`/`action_zoom_out` and `visit_bookmark` (via the pure `NoteTree.bookmark_context()` query) just call `update_location`; there is no per-site recording to remember. `mark_leaving` is guarded by context identity so a drifted search preview doesn't corrupt the pre-search entry. A new committed destination truncates any forward entries (like a browser).
- Search-result **cycling** previews context via `update_location(..., record=False)` (`widgets/info_sidebar.py`), so previews are not recorded; only a **selected** result (`accept_search`) records. Cursor-only moves (arrows, local `:random`, `?`) don't change context so aren't recorded.
- Back/forward apply results with `record=False` and skip entries whose node is no longer live (`_node_is_live` verifies child linkage up to the root, catching both delete — which unlinks without clearing `.parent` — and undo/redo deep-copy replacement). Reaching either end is a silent no-op.

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
- Audio feedback for timer events

## File Organization

```
src/
  forest.py           - Main app (ForestApp class, keybindings, command dispatch)
  note_tree.py        - NoteTree class (data model and persistence)
  node.py             - Node class (single note logic)
  note_tree_widget.py - NoteTreeWidget class (UI rendering)
  search_state.py     - SearchState dataclass (search mode state)
  timer.py            - Timer class (countdown timer with repeats)
  config.py           - Config class (settings management)
  sticky_notes.py     - StickyNotesScreen (board view for filtered notes)
  utils.py            - Helper functions (trigram search, substitutions)
  subtrees.py         - Predefined note templates
  themes.py           - Color theme definitions
  copied_list.py      - CopiedList helper (copy/paste/cycle logic; renders in sidebar)
  context_history.py  - ContextHistory helper (browser-style back/forward over context changes)
  clipboard.py        - OSC 52 system-clipboard write helper
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
- `` ` `` (backtick): Reveal/cycle the side panels. First press shows both the InfoSidebar (bookmarks) and the doodle pane; next press cycles the InfoSidebar (journal); next press hides both. The doodle pane is revealed/hidden together with the InfoSidebar via `` ` `` only (search/help open just the InfoSidebar).

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
- `y`: Yank cursor note text to system clipboard (OSC 52)
- `Y`: Yank cursor note + descendants to system clipboard (OSC 52)
- `r`: Renew the cursor note's `#T-` expiry timer (restart its countdown)
- `?`: Jump to the next open (leaf) question in the current context, wrapping back to the first after the last. "Open question" matches the InfoSidebar `leaf Q` count: a childless note whose text contains `?`, excluding `#DONE`/`#ARCHIVE`.
- `enter`: Add new note
- `0-9`: Jump to bookmark
- `alt+left` / `alt+right`: Context history back/forward (browser-style). Every committed context change (zoom, bookmark jump, search-result selection, `[[path]]` follow, random jump, etc.) is recorded to an in-memory list; back/forward step through it restoring both the context node and cursor. Search-result *cycling* (preview) is not recorded — only a selected result is. Stale entries (nodes removed by delete/undo) are skipped. See Context History below.
- `z`: Undo
- `Z`: Redo

## Logging

Application logs to `log.txt` in the project root. Use `logging.info()`, `logging.error()`, etc. for debugging.

## Theme

Custom theme defined in `forest_theme` (forest.py) with warm brown/orange color palette. Theme variables include custom colors for highlights (HL1-3), age gradients, and arrows.
