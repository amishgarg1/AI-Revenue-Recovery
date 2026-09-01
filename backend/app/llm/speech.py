"""
Turning a written script into a spoken one.

A voice template is rendered for the screen with the case's real figures —
"Rs 1,31,000.00", "25 days" — because that is what the message says. Handing
that string to a speech engine gets you "Rs one three one comma zero zero zero
point zero zero", which is not what a caller hears and not what the script
means.

So the same template is rendered twice from the same values: once with digits
for the transcript, once with words for the recording. They are the same
sentence, which is the point — the audio on the case page has to be the case's
own call, not a stand-in with somebody else's name in it.

Indian numbering throughout: lakh and crore, not million.
"""

import re

UNITS = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = [
    "", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
    "eighty", "ninety",
]


def _under_hundred(n: int) -> str:
    if n < 20:
        return UNITS[n]
    tens, unit = divmod(n, 10)
    return TENS[tens] + (f" {UNITS[unit]}" if unit else "")


def _under_thousand(n: int) -> str:
    hundreds, rest = divmod(n, 100)
    parts = []
    if hundreds:
        parts.append(f"{UNITS[hundreds]} hundred")
    if rest:
        parts.append(_under_hundred(rest))
    return " ".join(parts)


def number_to_words(n: int) -> str:
    """
    Indian numbering: crore, lakh, thousand, hundred.

    2_50_000 -> "two lakh fifty thousand", not "two hundred fifty thousand".
    """
    if n == 0:
        return "zero"
    if n < 0:
        return f"minus {number_to_words(-n)}"

    parts = []
    crore, n = divmod(n, 10_000_000)
    if crore:
        parts.append(f"{number_to_words(crore)} crore")
    lakh, n = divmod(n, 100_000)
    if lakh:
        parts.append(f"{_under_thousand(lakh)} lakh")
    thousand, n = divmod(n, 1_000)
    if thousand:
        parts.append(f"{_under_thousand(thousand)} thousand")
    if n:
        parts.append(_under_thousand(n))
    return " ".join(parts)


def rupees_to_words(text: str) -> str:
    """
    "Rs 1,31,000.00" -> "one lakh thirty one thousand rupees".

    Paise are dropped when they are zero, because nobody says "and zero paise",
    and spoken when they are not.
    """
    def replace(match: re.Match) -> str:
        digits = match.group(1).replace(",", "")
        whole, _, frac = digits.partition(".")
        words = f"{number_to_words(int(whole))} rupees"
        if frac and int(frac):
            words += f" and {number_to_words(int(frac))} paise"
        return words

    return re.sub(r"(?:Rs\.?|₹)\s*([\d,]+(?:\.\d+)?)", replace, text)


def identifier_to_words(text: str) -> str:
    """
    "inv_078" -> "oh seven eight".

    Read digit by digit, the way a person reads a reference number aloud. "Oh"
    rather than "zero" because that is how it is actually said.

    The word "invoice" is not added here: every template that carries an id
    already says it, and prepending another produced "invoice invoice oh seven
    eight".
    """
    spoken_digit = {"0": "oh", "1": "one", "2": "two", "3": "three", "4": "four",
                    "5": "five", "6": "six", "7": "seven", "8": "eight",
                    "9": "nine"}

    return re.sub(
        r"\binv[_-]?(\d+)\b",
        lambda m: " ".join(spoken_digit[d] for d in m.group(1)),
        text,
    )


def bare_numbers_to_words(text: str) -> str:
    """Whatever digits are left — a day count, an attempt number."""
    return re.sub(r"\b(\d+)\b", lambda m: number_to_words(int(m.group(1))), text)


def to_speech(text: str) -> str:
    """
    The written script as it should be spoken.

    Order matters: currency first so its digits are consumed before the bare
    -number pass can reach them, then identifiers, then anything left over.
    """
    spoken = rupees_to_words(text)
    spoken = identifier_to_words(spoken)
    spoken = bare_numbers_to_words(spoken)
    # Collapse the whitespace the substitutions leave behind.
    return re.sub(r"\s{2,}", " ", spoken).strip()
