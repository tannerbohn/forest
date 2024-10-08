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
        self.red = self.create_pair(self.create_color((255, 77, 0)), self.background)
        self.orange = self.create_pair(
            self.create_color((255, 123, 0)), self.background
        )
        self.yellow = self.create_pair(
            self.create_color((214, 166, 0)), self.background
        )
        self.green = self.create_pair(self.create_color((78, 91, 49)), self.background)
        self.purple = self.create_pair(
            self.create_color((147, 38, 255)), self.background
        )
        self.white = self.create_pair(
            self.create_color((255, 255, 255)), self.background
        )

        # useful resource: https://colorkit.io/
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

        # Note: for both age colouring and expiry colouring, its ordered by time. So for expiry, it starts at
        #   expiry_0, and gets closer to expiry_4 as the time draws closer
        self.expiry_0 = self.create_pair(
            self.create_color(colour_scheme["expiry_0"]), self.background
        )
        self.expiry_1 = self.create_pair(
            self.create_color(colour_scheme["expiry_1"]), self.background
        )
        self.expiry_2 = self.create_pair(
            self.create_color(colour_scheme["expiry_2"]), self.background
        )
        self.expiry_3 = self.create_pair(
            self.create_color(colour_scheme["expiry_3"]), self.background
        )
        self.expiry_4 = self.create_pair(
            self.create_color(colour_scheme["expiry_4"]), self.background
        )

        self.hashtag = self.create_pair(self.highlight, self.background)
        self.focus_arrow = self.bookmark
        self.nonfocus_arrow = self.age_3
        self.status_section = self.create_pair(self.highlight, self.light_background)
        self.collapse_indicator = self.create_pair(self.highlight_2, self.background)

        self.line_highlights = [
            self.create_pair(self.highlight, self.background),
            self.yellow,
            self.red,
        ]

        question_colour = self.highlight_2
        self.question = self.create_pair(question_colour, self.background)

    def create_color(self, color):
        r, g, b = get_rgb(color)
        # if isinstance(color, str) and color[0] == "#":
        #     color = color[1:]
        #     r, g, b = tuple(int(color[i : i + 2], 16) for i in (0, 2, 4))
        # else:
        #     r, g, b = color
        self.i += 1
        curses.init_color(
            self.i, int(1000 * r / 256), int(1000 * g / 256), int(1000 * b / 256)
        )
        return self.i

    def create_pair(self, foreground, background):
        self.i += 1
        curses.init_pair(self.i, foreground, background)
        return curses.color_pair(self.i)


def get_rgb(color_spec):
    if isinstance(color_spec, str) and color_spec[0] == "#":
        color_spec = color_spec[1:]
        r, g, b = tuple(int(color_spec[i : i + 2], 16) for i in (0, 2, 4))
    else:
        r, g, b = color_spec
    return r, g, b


def blend_colours(colour_a, colour_b, frac):
    rgb_a = get_rgb(colour_a)
    rgb_b = get_rgb(colour_b)
    r = int(rgb_a[0] * (1 - frac) + rgb_b[0] * frac)
    g = int(rgb_a[1] * (1 - frac) + rgb_b[1] * frac)
    b = int(rgb_a[2] * (1 - frac) + rgb_b[2] * frac)

    return (r, g, b)
