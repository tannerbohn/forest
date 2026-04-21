from textual.suggester import Suggester

from subtrees import SUBTREES


class MultiPurposeSuggester(Suggester):

    def __init__(self, mode="command"):
        super().__init__()
        self.mode = mode  # "command" or "edit"
        if self.mode == "command":
            self.placeholder = (
                "help | bookmark | run | timer <duration> | insert <name> | "
                "j+ <text> | collapse | ?/?* <query> | random/random* | sn/sn* [filter] | snr | "
                "archive set|unset|show|hide | doodle show|hide|clear"
            )
        else:
            self.placeholder = ""

    async def get_suggestion(self, value: None | str) -> None | str:

        if self.mode == "edit":
            # Suggestions for editing notes
            if not value:
                return None

            # Suggest hashtags
            if value.endswith("#"):
                return value + "T- | #sum | #max | #min | #avg"

            # Suggest value syntax
            if value.endswith("$"):
                return (
                    value + "variable=value | $variable_inc=value | $variable_dec=value"
                )

            return None

        # Command mode suggestions
        if not value:
            # Show all available commands with syntax hints
            return self.placeholder

        # Smart auto-completion for partial commands
        value_lower = value.lower()

        if "help".startswith(value_lower):
            return "help"

        if "bookmark".startswith(value_lower):
            return "bookmark"

        if "run".startswith(value_lower):
            return "run"

        if "j+".startswith(value_lower):
            return "j+ <journal entry text>"

        if value == "?":
            return "? <local query regex> | ?*/?? <global query regex> | (use empty query to find similar notes)"
        if value in ["?*", "??"]:
            return (
                value
                + " <global query regex> | (use empty query to find similar notes)"
            )

        # Show example durations when user types "timer "
        if "timer ".startswith(value_lower):
            return "timer 5m | 25m | 1h | 5m 3x | cancel"

        if "timer cancel".startswith(value_lower):
            return "timer cancel"

        if value_lower == "snr":
            return "snr"
        if "collapse".startswith(value_lower):
            return "collapse"

        if "random".startswith(value_lower):
            return "random (context) | random* (global)"

        if "sn".startswith(value_lower):
            return "sn [filter] (context) | sn* [filter] (global) | snr (recover)"

        if "archive ".startswith(value_lower) or value_lower.startswith("archive"):
            # Filter optoins based on what's been typed
            partial = value[8:]  # Get text after "archive "
            matching = [
                name
                for name in ["set", "unset", "show", "hide"]
                if name.startswith(partial)
            ]
            if matching:
                return "archive " + " | ".join(sorted(matching))

        # Show and filter subtree options when user types "insert"
        if "insert ".startswith(value_lower) or value_lower.startswith("insert"):
            # Filter subtrees based on what's been typed
            partial = value[7:].upper()  # Get text after "insert "
            matching = [name for name in SUBTREES.keys() if name.startswith(partial)]
            if matching:
                return "insert " + " | ".join(sorted(matching))

        if "doodle ".startswith(value_lower) or value_lower.startswith("doodle"):
            # Filter optoins based on what's been typed
            partial = value[7:]  # Get text after "doodle "
            matching = [
                name for name in ["show", "hide", "clear"] if name.startswith(partial)
            ]
            if matching:
                return "doodle " + " | ".join(sorted(matching))

        return None
