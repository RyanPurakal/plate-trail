"""Synthetic plates and the look-alike character table used for misreads.

Plates follow the shape of current New Jersey passenger plates (letter,
two digits, three letters, e.g. "D12ABC") so misreads exercise a realistic
mix of letters and digits. They are generated at random; any match with a
real plate is coincidental, and no real plate data is ever used.
"""

import string

import numpy as np

# ASSUMPTION: which characters ALPR OCR confuses. Chosen from visual
# similarity on plate fonts, not from a measured confusion matrix. A misread
# replaces a character only with one of its listed look-alikes.
LOOKALIKES: dict[str, tuple[str, ...]] = {
    "0": ("O", "D", "Q"),
    "O": ("0", "D", "Q"),
    "D": ("0", "O"),
    "Q": ("0", "O"),
    "1": ("I", "7"),
    "I": ("1",),
    "7": ("1",),
    "2": ("Z",),
    "Z": ("2",),
    "5": ("S",),
    "S": ("5",),
    "6": ("G",),
    "G": ("6",),
    "8": ("B",),
    "B": ("8",),
}

PLATE_PATTERN = "LDDLLL"  # L = letter, D = digit


def synthetic_plate(rng: np.random.Generator, pattern: str = PLATE_PATTERN) -> str:
    chars = []
    for kind in pattern:
        pool = string.ascii_uppercase if kind == "L" else string.digits
        chars.append(pool[int(rng.integers(len(pool)))])
    return "".join(chars)


def misread(plate: str, rng: np.random.Generator, p_char: float) -> str:
    """Independently swap each character for a look-alike with probability p_char.

    One uniform is drawn per character whether or not it has look-alikes, so
    a character's outcome doesn't depend on its neighbours' draws.
    """
    out = []
    for ch, u in zip(plate, rng.random(len(plate))):
        options = LOOKALIKES.get(ch)
        if options and u < p_char:
            out.append(options[int(rng.integers(len(options)))])
        else:
            out.append(ch)
    return "".join(out)
