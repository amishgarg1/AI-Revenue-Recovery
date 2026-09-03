"""
Written-to-spoken conversion.

The screen shows a case's real figures and the recording has to say the same
ones. Getting that wrong is not cosmetic: an earlier build played one specimen
clip on every voice case, so the page read one customer's name and the speaker
said another's.
"""

import pytest

from app.llm.speech import (
    bare_numbers_to_words, identifier_to_words, number_to_words,
    rupees_to_words, to_speech,
)


@pytest.mark.parametrize("n,words", [
    (0, "zero"),
    (7, "seven"),
    (13, "thirteen"),
    (25, "twenty five"),
    (100, "one hundred"),
    (101, "one hundred one"),
    (999, "nine hundred ninety nine"),
    (1_000, "one thousand"),
    (99_079, "ninety nine thousand seventy nine"),
])
def test_numbers_below_a_lakh(n, words):
    assert number_to_words(n) == words


@pytest.mark.parametrize("n,words", [
    # The reason this module exists rather than a generic humaniser: Indian
    # numbering groups by lakh and crore, so 1,31,000 is "one lakh thirty one
    # thousand", never "one hundred thirty one thousand".
    (1_00_000, "one lakh"),
    (1_31_000, "one lakh thirty one thousand"),
    (1_41_922, "one lakh forty one thousand nine hundred twenty two"),
    (12_00_000, "twelve lakh"),
    (1_00_00_000, "one crore"),
    (2_50_00_000, "two crore fifty lakh"),
])
def test_indian_grouping(n, words):
    assert number_to_words(n) == words


def test_rupee_figures_become_words():
    assert rupees_to_words("Rs 1,31,000.00") == "one lakh thirty one thousand rupees"
    assert rupees_to_words("₹8,400.00") == "eight thousand four hundred rupees"


def test_zero_paise_are_not_read_out():
    """Nobody says "and zero paise"."""
    assert "paise" not in rupees_to_words("Rs 500.00")


def test_real_paise_are_read_out():
    assert rupees_to_words("Rs 500.50") == "five hundred rupees and fifty paise"


def test_invoice_ids_are_read_digit_by_digit():
    """A reference number is spelled, not counted: "oh seven eight", not 78."""
    assert identifier_to_words("invoice inv_078") == "invoice oh seven eight"


def test_the_word_invoice_is_not_duplicated():
    """
    Every template that carries an id already says "invoice". Adding another
    produced "invoice invoice oh seven eight".
    """
    assert identifier_to_words("invoice inv_062").count("invoice") == 1


def test_bare_numbers_become_words():
    assert bare_numbers_to_words("25 days") == "twenty five days"


def test_a_whole_script_converts_without_leaving_digits():
    written = (
        "Namaste Sanya Bose ji. Aapka invoice inv_078, amount Rs 1,31,000.00, "
        "25 din se pending hai. Ek dabaiye, nau dabaiye."
    )
    spoken = to_speech(written)

    assert not any(ch.isdigit() for ch in spoken), spoken
    # The name and the merchant survive untouched — only numbers change.
    assert "Sanya Bose" in spoken
    assert "one lakh thirty one thousand rupees" in spoken
    assert "twenty five din" in spoken


def test_currency_is_converted_before_bare_numbers_can_reach_it():
    """
    Order matters. If the bare-number pass ran first it would turn "1" and
    "31" and "000" into words separately and the amount would be nonsense.
    """
    spoken = to_speech("Rs 1,31,000.00 pending")
    assert "one lakh thirty one thousand rupees" in spoken
    assert "one thirty one" not in spoken


def test_conversion_leaves_no_double_spaces():
    assert "  " not in to_speech("Rs 500.00  and  inv_001")
