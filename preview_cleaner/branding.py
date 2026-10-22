"""Local vector identity for the liturgical workspace; never added to PDFs."""


def draw_cantus_mark(canvas, x, y, scale=1, chapel=False):
    """Draw a Latin cross whose lower stem resolves into a musical note."""
    def points(*coords):
        return tuple((x if i % 2 == 0 else y) + value * scale
                     for i, value in enumerate(coords))

    if chapel:
        # A quiet pointed chapel arch frames the mark in the welcome state.
        canvas.create_line(*points(-30, 27, -30, -8, -22, -22, 0, -34,
                                   22, -22, 30, -8, 30, 27),
                           fill='#bfc8b8', width=max(1, scale))
        for offset in range(-5, 28, 8):
            canvas.create_line(*points(-66, offset, 66, offset),
                               fill='#d0d1c2', width=1)
    canvas.create_line(*points(0, -25, 0, 19), fill='#263f38',
                       width=max(2, 2.5 * scale))
    canvas.create_line(*points(-12, -11, 12, -11), fill='#263f38',
                       width=max(2, 2.5 * scale))
    canvas.create_oval(*points(-11, 15, 1, 23), fill='#994128', outline='')
