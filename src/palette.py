import curses


class Palette:
    i = 50  # do not start at 0, because on some terminals, it messes up colours

    def __init__(self, stdscr, colour_scheme):
        self.background = self.create_color(colour_scheme["background"])
        self.light_background = self.create_color(colour_scheme["top_bar_background"])

        self.default_text = self.create_color(colour_scheme["default_text"])
        self.highlight = self.create_color(colour_scheme["primary_highlight"])
        self.highlight_2 = self.create_color(colour_scheme["secondary_highlight"])

        # set the default background and foreground
        stdscr.bkgd(" ", self.create_pair(self.default_text, self.background))

        self.top_bar = self.create_pair(self.default_text, self.light_background)

        self.bookmark = self.create_pair(self.highlight_2, self.background)
        self.yellow = self.create_pair(
            self.create_color((255, 255, 0)), self.background
        )

        self.age_0_colour = self.create_color(colour_scheme["age_0"])
        self.age_1_colour = self.create_color(colour_scheme["age_1"])
        self.age_2_colour = self.create_color(colour_scheme["age_2"])
        self.age_3_colour = self.create_color(colour_scheme["age_3"])
        self.age_4_colour = self.create_color(colour_scheme["age_4"])

        self.age_0 = self.create_pair(self.age_0_colour, self.background)
        self.age_1 = self.create_pair(self.age_1_colour, self.background)
        self.age_2 = self.create_pair(self.age_2_colour, self.background)
        self.age_3 = self.create_pair(self.age_3_colour, self.background)
        self.age_4 = self.create_pair(self.age_4_colour, self.background)

        self.hashtag = self.create_pair(self.highlight, self.background)
        self.focus_arrow = self.bookmark
        self.nonfocus_arrow = self.age_3
        self.status_section = self.create_pair(self.highlight, self.light_background)
        self.collapse_indicator = self.create_pair(self.highlight_2, self.background)

        question_colour = self.highlight_2
        self.question = self.create_pair(question_colour, self.background)

    def create_color(self, color):
        if isinstance(color, str) and color[0] == "#":
            color = color[1:]
            r, g, b = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
        else:
            r, g, b = color
        self.i += 1
        curses.init_color(
            self.i, int(1000 * r / 256), int(1000 * g / 256), int(1000 * b / 256)
        )
        return self.i

    def create_pair(self, foreground, background):
        self.i += 1
        curses.init_pair(self.i, foreground, background)
        return curses.color_pair(self.i)
