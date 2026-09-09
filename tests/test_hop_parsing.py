"""
The parse table from the hop-budget contract (sc-264), case for case.

Every one of these is a zero. The default is the whole safety property: a ring
in which a missing or unreadable budget meant "unlimited" would spin forever on
the box that is simultaneously being measured.
"""

from django.test import SimpleTestCase

import mesh

# The contract's table, verbatim, plus the values Python specifically gets
# wrong if the header is handed to int().
ZERO_CASES = [
    ("absent", None),
    ("empty", ""),
    ("letters", "abc"),
    ("decimal", "1.5"),
    ("hex", "0x4"),
    # int("+4") == 4. The table says 0, and the table wins.
    ("explicit plus", "+4"),
    ("word", "four"),
    ("negative one", "-1"),
    ("negative hundred", "-100"),
    ("zero", "0"),
    ("whitespace only", "   "),
    ("tab only", "\t"),
    ("newline only", "\n"),
    # int("4_0") == 40 in Python: PEP 515 underscores are accepted by int().
    ("underscored", "4_0"),
    # int() accepts non-ASCII decimal digits; a header is not a place for them.
    ("arabic-indic digits", "\u0664"),
    # str.strip() with no argument eats U+00A0 too. The contract says ASCII
    # whitespace, so a NBSP-padded value is not a number.
    ("nbsp padded", "\u00a04"),
    ("trailing junk", "4x"),
    ("leading junk", "x4"),
]


class ParseHopsZeroCasesTest(SimpleTestCase):
    def test_every_zero_case_in_the_contract_table(self):
        for label, raw in ZERO_CASES:
            with self.subTest(case=label, raw=raw):
                self.assertEqual(mesh.parse_hops(raw), 0)


class ParseHopsAcceptedTest(SimpleTestCase):
    def test_plain_integer(self):
        self.assertEqual(mesh.parse_hops("4"), 4)

    def test_leading_and_trailing_ascii_whitespace_is_trimmed(self):
        self.assertEqual(mesh.parse_hops(" 4 "), 4)
        self.assertEqual(mesh.parse_hops("\t4\r\n"), 4)

    def test_leading_zeros(self):
        self.assertEqual(mesh.parse_hops("004"), 4)

    def test_first_value_wins_when_the_header_repeats(self):
        # PEP 3333 lets a WSGI server fold repeated headers into one
        # comma-separated value, and waitress does exactly that, so by the time
        # Django hands the value over the individual headers are gone. Taking
        # the part before the first comma is what "use the first value" has to
        # mean here.
        self.assertEqual(mesh.parse_hops("4, 8"), 4)
        self.assertEqual(mesh.parse_hops("8,4"), 8)
        self.assertEqual(mesh.parse_hops("abc,4"), 0)

    def test_clamped_to_sixty_four(self):
        self.assertEqual(mesh.parse_hops("64"), 64)
        self.assertEqual(mesh.parse_hops("65"), 64)
        self.assertEqual(mesh.parse_hops("1000000"), 64)
        # A typo is clamped, never rejected: the load driver has no failure
        # mode to handle here.
        self.assertEqual(mesh.parse_hops("9" * 500), 64)
