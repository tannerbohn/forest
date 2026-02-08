"""
Theme definitions for Forest note-taking app.

To switch themes, set default_theme in config.json
"""

from textual.theme import Theme

# ============================================================================
# FOREST (Default)
# ============================================================================
forest_bkg = "#120e0a"  # background color
forest = Theme(
    name="forest",
    primary="#23332B",  # background of selected line of info table
    foreground="#b5af9c",  # default text color
    background=forest_bkg,  # shows up in scroll bar and behind help menu
    surface=forest_bkg,  # main background
    panel="#283323",  # "#382c1e", #"#4a3a26",  # header and footer background
    variables={
        "block-cursor-text-style": "none",
        "block-cursor-blurred-text-style": "none",
        "footer-key-foreground": "white",
        "input-selection-background": "white 15%",
        "dim-text": "#544d3d",  # when a note is marked complete
        "HL1": "#039ad7",  # "#00b3ff",  # first (and most common) highlight text color
        "HL2": "#dca708",  # "#f3a712",  # second highlight text color (for "ideas")
        "HL3": "#c44f1f",  # "#db452b",  # third highlight text color (for high-important)
        "cursor-arrow": "white",  # current-line indicator
        "default-arrow": "#746652",  # default line marker halfway between HL1 and background
        "age-color-0": "#b5af9c",  # far-left indicator strip color for new notes
        "age-color-1": "#78715d",
        "age-color-2": "#2a261e",
        "age-column-bg": forest_bkg,  # indicator strip color for oldest notes
    },
)

pine_bkg = "#181a18"  # "#1f170d"
pine = Theme(
    name="pine",
    primary="#ffffff",  # unused?
    foreground="#aeb0ae",  # default text
    background=pine_bkg,  # shows up in scroll bar and behind help menu
    surface=pine_bkg,  # main background
    panel="#263022",  # header and footer background
    variables={
        "block-cursor-text-style": "none",
        "block-cursor-blurred-text-style": "none",
        "footer-key-foreground": "white",
        "input-selection-background": "white 15%",
        "dim-text": "#545654",  # when a note is marked complete
        "HL1": "#5d9c33",  # first highlight text color (and line count in top bar)
        "HL2": "#2792c4",  # second highlight text color
        "HL3": "#8c3545",  # third highlight text color
        "cursor-arrow": "white",  # current-line indicator triangle
        "default-arrow": "#475841",  # halfway between HL1 and background
        "age-color-0": "#388038",  # far-left indicator strip color for new notes
        "age-color-1": "#3f5627",
        "age-color-2": "#181a18",
        "age-column-bg": pine_bkg,  # indicator strip color for oldest notes
    },
)


coral_bkg = "#151c33"
coral = Theme(
    name="coral",
    primary="#4a3a26",  # background of mouse-overed line
    foreground="#b3af8f",  # default text
    background=coral_bkg,  # shows up in scroll bar and behind help menu
    surface=coral_bkg,  # main background
    panel="#2b3a67",  # header and footer background
    variables={
        "block-cursor-text-style": "none",
        "block-cursor-blurred-text-style": "none",
        "footer-key-foreground": "white",
        "input-selection-background": "white 15%",
        "dim-text": "#494e51",  # when a note is marked complete
        "HL1": "#f79256",  # first highlight text color (and line count in top bar)
        "HL2": "#4dd1a9",  # "#66a85b", #"#f3a712",  # second highlight text color
        "HL3": "#00b2ca",  # "#d4ae33", #"#db2b39",  # third highlight text color
        "cursor-arrow": "white",  # current-line indicator triangle
        "default-arrow": "#66999b",  # halfway between HL1 and background
        "age-color-0": "#ffc482",  # far-left indicator strip color for new notes
        "age-color-1": "#087dae",
        "age-color-2": "#10475d",
        "age-column-bg": coral_bkg,  # indicator strip color for oldest notes
    },
)


# ============================================================================
# VERVE - Cool purple/neon palette with creative spark accents
# ============================================================================
verve = Theme(
    name="verve",
    primary="#4d2b5e",  # Rich plum; provides a deep but "living" foundation
    foreground="#e0def4",  # Soft lavender-white; reduces eye strain while maintaining the cool tone
    background="#191724",  # Desaturated midnight; provides high contrast for neon accents
    surface="#191724",  # Consistent deep backdrop
    panel="#26233a",  # Slightly lighter indigo for structural distinction
    variables={
        "block-cursor-text-style": "none",
        "block-cursor-blurred-text-style": "none",
        "footer-key-foreground": "#eb6f92",  # Punchy rose accent
        "input-selection-background": "white 20%",
        "dim-text": "#6e6a86",  # Muted slate for completed tasks
        "HL1": "#9ccfd8",  # Ethereal foam green (Creative Spark 1)
        "HL2": "#f6c177",  # Saffron/Gold (Creative Spark 2)
        "HL3": "#eb6f92",  # Energetic Rose (Creative Spark 3)
        "cursor-arrow": "#c4a7e7",  # Bright lilac indicator
        "default-arrow": "#56526e",  # Low-profile bridge between primary and background
        "age-color-0": "#ebbcba",  # Soft coral for new notes
        "age-color-1": "#31748f",  # Deep pine for mid-age
        "age-color-2": "#191724",  # Matching background for oldest notes
        "age-column-bg": "#191724",
    },
)


# ============================================================================
# FOREST V2 - Warm organic cozy forest
# ============================================================================
forest_v2_bkg = "#110d08"  # rich dark soil
forest_v2 = Theme(
    name="forest_v2",
    primary="#2b2418",  # warm brown for selected line in info table
    foreground="#c4b99a",  # aged parchment by firelight
    background=forest_v2_bkg,  # deep soil
    surface=forest_v2_bkg,  # main background
    panel="#2a2215",  # warm bark-brown header/footer
    variables={
        "block-cursor-text-style": "none",
        "block-cursor-blurred-text-style": "none",
        "footer-key-foreground": "white",
        "input-selection-background": "white 15%",
        "dim-text": "#4a4232",  # fallen leaves - completed notes
        "HL1": "#3d8db5",  # moss/sage green - primary highlight
        "HL2": "#d4a843",  # dappled sunlight - ideas
        "HL3": "#c45a2a",  # glowing embers - high importance
        "cursor-arrow": "white",  # current-line indicator
        "default-arrow": "#6b5d45",  # warm brown line marker
        "age-color-0": "#8aad6e",  # new growth - fresh notes
        "age-color-1": "#6b5d45",  # aging bark
        "age-color-2": "#1a1610",  # fading into dark earth
        "age-column-bg": forest_v2_bkg,  # age strip background
    },
)

# ============================================================================
# Theme Registry
# ============================================================================
# All available themes - these will be registered with Textual
THEMES = {
    "forest": forest,
    "forest_v2": forest_v2,
    "pine": pine,
    "verve": verve,
    "coral": coral,
}

# ============================================================================
# Regex-based Text Coloring
# ============================================================================
# List of (pattern, formatting) tuples for applying regex-based text formatting
# https://textual.textualize.io/guide/content/
#
# Examples:
# - (r"\?", "#ff4d00") - Color all question marks orange
# - (r"@\w+", "bold") - make @mentions bold
#
# Note: Patterns are applied in order
TEXT_COLOR_REGEX_LIST = [
    (r"^ (\!.*)", "#919191"),
    (r"\?\?", "bold"),
    (r"\?", "#ffffff"),
    (r"\b\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?\b", "dim"),
    (r"\*.*\*", "bold"),
    # (r"TODO|FIXME", "#ff0000"),  # Color TODO/FIXME red
    # (r"(?i)\b(What|How|Why|If|Could|Is)\b", "bold"),
]
