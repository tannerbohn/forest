# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Overview

Forest is a minimal tree-based note-taking TUI built with Textual. Users create, edit, and navigate hierarchical notes stored as tab-indented text files. The guiding intent is to be **minimally distracting**: features should stay out of the way.

## Design questions for any change

Before planning or making a change, ask:
- Can this be solved by **subtraction or generalization** of an existing feature/limitation, rather than adding something new?
- How has **nature** already solved this problem?
- Does the solution align with Forest's intent of being **minimally distracting**?

## Maintaining this file

Keep this a durable, high-level map — not a changelog. Update it when the **architecture, behavioral rules, or file layout** change meaningfully. Do **not** update it for routine edits already covered by a pointer (key bindings, command names, config keys); those live in the source, and this file only points at them. Prefer describing stable *behavior and intent* over churning *mechanism*.

## Setup and Development

Install: `python3 -m pip install -r requirements.txt`

Run: `python3 src/forest.py trees/intro.txt` (create a new tree by `touch`-ing a file first).

Configuration lives in `config.json` at the project root (copy from `config.json.example`); defaults are used if it's missing. `src/config.py` is the authoritative list of settings and defaults — theme, log level, undo depth, auto-save, scroll margin, and `margin_width` (the reserved right/left strip for the InfoSidebar and doodle pane). See that file rather than duplicating the key list here.

Logs go to `log.txt` in the project root (`logging.info()`, etc.).

## Architecture

### Core data model

- **Node (`node.py`)** — a single note: text, depth, collapse state, creation time, parent/children. Understands hashtags (`#DONE`, `#HL1-3`, `#T-…`) and `$variable=value` extraction for aggregation.
- **NoteTree (`note_tree.py`)** — the whole tree plus persistence, bookmarks, journal, and the **context node** (which branch is currently visible). Loads/saves tab-indented text with inline metadata.
- **NoteTreeWidget (`note_tree_widget.py`)** — virtualized display (Textual `ScrollView` + Line API). Derives a flat list of `VisualRow`s from `visible_node_list` (wrapping resolved up front, per-node results cached) and paints only viewport rows. Styling-only changes repaint in place rather than rebuilding.
- **Config (`config.py`)** — settings loaded from `config.json`, with defaults.

### Persistence format

Each line: `<tabs><prefix> <text> @{YYYY-MM-DD[,b#][,x]}`, where the `-`/`+` prefix is expanded/collapsed and the `@{…}` suffix stores creation date, optional bookmark slot (`b0`-`b9`), and optional context marker (`x`). Metadata is written by the app — don't hand-author `@{…}` suffixes.

### Application flow

Config → `ForestApp` loads a tree file → `NoteTree` parses it → `NoteTreeWidget` renders visible nodes → keyboard interaction → save back to text with inline metadata.

### Key concepts

- **Context node** — the focused branch. Zooming in/out changes it, changing what's visible.
- **Multiline rendering** — long notes wrap across screen rows; each wrap segment is its own `VisualRow` (first segment bears the arrow, later ones align under the text).
- **Node state** — persisted inline per line (see format above): collapse, bookmarks, context flag, creation date.

## Interaction

Key bindings and commands are defined in the source and change often, so they are **not enumerated here**. The authoritative lists are:
- App-level bindings: `ForestApp.BINDINGS` (`src/forest.py`)
- Tree bindings: `NoteTreeWidget.BINDINGS` (`src/note_tree_widget.py`)
- Command-mode commands: `_COMMAND_REGISTRY` (`src/forest.py`)

Categories of interaction: navigation/zoom (arrows), editing, highlight/done cycling, bookmarks (digit visits a slot, shift+digit assigns), copy/paste/link/yank, undo/redo, context-history back/forward, and **command mode** (`:`). Command mode also handles the `?`/`?*`/`??` search prefix (local/global/similarity). The `` ` `` (backtick) key reveals and cycles the side panels (InfoSidebar and doodle pane).

## Special features

### Hashtags
- `#DONE` — marks complete, dims in UI.
- `#HL1`/`#HL2`/`#HL3` — color highlighting.
- `#T-<duration>` — expiring note (see below).
- `#sum`/`#max`/`#min`/`#avg` — aggregate child `$variable` values.

### Value system
- `$variable=value` sets a value; `$variable_inc=value` / `$variable_dec=value` auto-adjust on toggle-done. Aggregation hashtags compute over descendant values.

### Expiring notes
- Tag a note `#T-<duration>` (e.g. `#T-7d`, `#T-30m`, `#T-2mo`, `#T-1y`; parsed by `extended_parse` in `node.py`, which adds `mo`/`y`). On first parse the tag is rewritten to include the computed absolute expiry so it's stable across reloads; the `#T-…` token is hidden from displayed text.
- A timer note shows a color-coded **`T`** in the gutter and an inline readout (`⏳2d` counting down, `⌛3d ago` once expired). Expired notes are **not deleted** — the line is dimmed/reddened. Press `r` to renew (restart the countdown; undoable).
- `#T-*<duration>` **auto-renews**: on expiry it re-arms for another cycle (shows `↺`). Auto-renew is not pushed to the undo stack.
- If an expiring note is also a **command note** (text starts with `!`), the command runs automatically on expiry. With auto-renew this is cron-like (`!backup.sh #T-*1d` runs daily). Forest control tokens are stripped before the shell sees the command.
- Invariants: all timer notes live in the global `NoteTree.timer_nodes` registry. Expiry is checked on a frequent (~10s) tick over that small registry; the registry itself is rebuilt on a slower (~60s) cadence, so a new `#T-` note enters within ~60s. Notes already expired at load are pre-marked — **no backfill** of missed notifications or lapsed commands on open. Timer notes also appear in an **Expiring** section of the bookmarks side panel, soonest first.

### Context history
- Browser-style back/forward over context changes (`alt+left`/`alt+right`). In-memory only, not persisted. Owned by `NoteTreeWidget` as `context_history` (`context_history.py`).
- **Invariant:** `NoteTreeWidget.update_location(context_node, line_node=None, record=True)` is the single navigation primitive — the only method that changes the context — so all history logic lives there. Every navigation (zoom, bookmark jump, accepted search, `[[path]]` follow, random) routes through it. Search-result *cycling* previews with `record=False` and is not recorded; only a selected result is. Stale entries (nodes removed by delete/undo) are skipped.

### Bookmarks
- Digit `0`-`9` visits a slot; `shift`+digit assigns a bookmark to the cursor note. When all 10 slots are full, the least-recently-used is replaced. Shown with 💠 in the left margin.

### Journal
- `:j+ <text>` adds a timestamped entry, auto-creating Journal → Year → Month hierarchy. Entries formatted `[YYYY-MM-DD HH:MM] text`.

### Search
- `:?<query>` (local), `:?*<query>` / `:??<query>` (global), `:?` (empty → notes similar to the cursor). Trigram similarity (`utils.py`); path matching with `>` (e.g. `?Parent>Child`). Arrows navigate results, Enter accepts, Escape cancels.

### Subtrees
- `:insert <name>` inserts a predefined template (defined in `subtrees.py`).

### Sticky notes
- `:sn` / `:sn*` (local/global) open a board of highlighted notes, optionally filtered by `#HL1`/`#HL2`/`#HL3` or regex; `:snr` reopens the last board.

### Input substitutions
- `{NOW}` → current timestamp `[YYYY-MM-DD HH:MM]`.

### Sound effects
- Audio feedback for timer events.

### External file sync
- While a tree is open, Forest polls the file's mtime (config
  `external_reload_interval` seconds; `0` disables) and pulls in edits made by
  other programs. Reload never happens mid-edit or mid-search (deferred to a
  later tick).
- Reconciliation is **content-aware**, not last-writer-wins: with no unsaved
  in-app edits it reloads; with unsaved edits it does a line-level **3-way merge**
  (base / local / disk, `three_way_merge` in `utils.py`) so disjoint external and
  local changes are both kept. Only a genuine overlapping conflict drops the local
  side — and even then the pre-reload tree is seeded as a single **undo** step, so
  `undo` restores it. `:reload` forces the same reconcile on demand.
- Mechanism lives in `ForestApp._check_external_change` / `_reconcile_disk`
  (`forest.py`) over `NoteTree.apply_lines` / `apply_external` / `serialize_lines`
  and the `_base_lines`/`_disk_mtime` baseline (`note_tree.py`). The baseline is
  refreshed on every load and save so Forest's own writes aren't seen as external.

## File organization

```
src/
  forest.py            - ForestApp: main app, keybindings, command dispatch (_COMMAND_REGISTRY)
  note_tree.py         - NoteTree: data model and persistence
  node.py              - Node: single-note logic
  note_tree_widget.py  - NoteTreeWidget: virtualized rendering, navigation, context history
  search_state.py      - SearchState dataclass
  timer.py             - Timer: countdown with repeats
  config.py            - Config: settings
  sticky_notes.py      - StickyNotesScreen: board view for filtered notes
  utils.py             - helpers (trigram search, substitutions, sound)
  subtrees.py          - predefined note templates
  themes.py            - color theme definitions
  context_history.py   - ContextHistory: back/forward helper
  clipboard.py         - OSC 52 system-clipboard write
  notifications.py     - desktop notification helpers
  forest.tcss, text_overflow.tcss - Textual stylesheets
  widgets/
    status_bar.py         - StatusBar (context path, save indicator, timer)
    info_sidebar.py       - InfoSidebar (bookmarks, copied, expiring, journal, search, help)
    doodle_pane.py        - DoodlePane (per-tree doodle canvas)
    command_info_panel.py - CommandInfoPanel (command-mode help)
    suggesters.py         - MultiPurposeSuggester (command/edit completion)

trees/                 - note files (intro.txt is the example)
config.json            - user configuration (optional; defaults if missing)
config.json.example    - template
```

## Theme

Custom `forest_theme` (`forest.py`) with a warm brown/orange palette; variables include highlight (HL1-3) and age-gradient colors. Additional themes in `themes.py`.
