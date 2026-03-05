"""
Theme definitions for Forest note-taking app.

To switch themes, set default_theme in config.json
"""

from textual.theme import Theme

# ============================================================================
# FOREST (Default) - warm cozy forest with unique electric blue highlight
# ============================================================================
forest_bkg = "#110d08"  # rich dark soil
forest = Theme(
    name="forest",
    primary="#2b2418",  # warm brown for selected line in info table
    secondary="#18aee9",  # same as HL1
    foreground="#d0c6a8",  # aged parchment by firelight
    background=forest_bkg,  # deep soil
    surface=forest_bkg,  # main background
    panel="#2a2215",  # warm bark-brown header/footer
    variables={
        "block-cursor-text-style": "none",
        "block-cursor-blurred-text-style": "none",
        "footer-key-foreground": "white",
        "input-selection-background": "white 15%",
        "dim-text": "#4a4232",  # fallen leaves - completed notes
        "HL1": "#18aee9",  # vivid sky blue - primary highlight
        "HL2": "#deb650",  # dappled sunlight - ideas
        "HL3": "#d16835",  # glowing embers - high importance
        "cursor-arrow": "white",  # current-line indicator
        "default-arrow": "#6b5d45",  # warm brown line marker
        "age-color-0": "#8aad6e",  # new growth - fresh notes
        "age-color-1": "#6b5d45",  # aging bark
        "age-color-2": "#1a1610",  # fading into dark earth
        "age-column-bg": forest_bkg,  # age strip background
        "find-text-bg": "#4d4130",  # warm amber background for :f matches
        "SNBG0": "#d8c8a0",  # birch bark parchment
        "SNBG1": "#9cc88c",  # moss / fern frond
        "SNBG2": "#e8c060",  # honey lamplight
        "SNBG3": "#d89878",  # autumn terracotta
        "SNBG4": "#c4d4a8",  # sage lichen
        "SNBG5": "#88b8c0",  # misty creek
        "SNBGR": "#2a2215",  # warm bark (matches panel)
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
        "find-text-bg": "#3d3460",  # rich purple background for :f matches
        "SNBG0": "#9ccfd8",  # foam green
        "SNBG1": "#eb6f92",  # energetic rose
        "SNBG2": "#f6c177",  # saffron gold
        "SNBG3": "#c4a7e7",  # bright lilac
        "SNBG4": "#ebbcba",  # soft coral
        "SNBG5": "#3e8fb0",  # deep teal-blue
        "SNBGR": "#26233a",  # indigo panel (matches panel)
    },
)


# ============================================================================
# Theme Registry
# ============================================================================
# All available themes - these will be registered with Textual
THEMES = {
    "forest": forest,
    "verve": verve,
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
    (r"^ (>.*)", "dim"),
    (r"(\[\[.*?\]\])", "dim"),
    (r"::", "dim"),
    # (r"(\[\[.*?\]\])", "u"),
    # (r"TODO|FIXME", "#ff0000"),  # Color TODO/FIXME red
    # (r"(?i)\b(What|How|Why|If|Could|Is)\b", "bold"),
]
