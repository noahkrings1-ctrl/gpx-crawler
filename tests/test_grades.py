import pytest

from parsers.grades import (
    TOUR_TYPES,
    grade_matches,
    grade_terms,
    is_grade,
    scale_from_title,
    split_grade,
    tour_type,
)


# --- Exakter Stufenvergleich ----------------------------------------------


@pytest.mark.parametrize(
    "value", ["T4", "T4-", "T4+", "T4 - Alpinwandern", "T4- - Alpinwandern", "t4"]
)
def test_t4_matches_its_whole_family(value: str) -> None:
    assert grade_matches(value, "T4")


@pytest.mark.parametrize("value", ["T5", "T3+", "WS", None, ""])
def test_t4_does_not_match_other_grades(value) -> None:
    assert not grade_matches(value, "T4")


def test_single_letters_no_longer_match_inside_longer_grades() -> None:
    """Als Teiltext steckte S in WS und ZS, der Filter traf fast jede Hochtour."""
    for value in ("S", "S-", "S+"):
        assert grade_matches(value, "S")
    for value in ("WS", "ZS", "SS", "ZS+"):
        assert not grade_matches(value, "S")


def test_modifier_in_the_term_must_match_exactly() -> None:
    assert grade_matches("ZS+", "ZS+")
    assert not grade_matches("ZS", "ZS+")
    assert not grade_matches("ZS-", "ZS+")


def test_climbing_grades_are_not_confused() -> None:
    assert grade_matches("II (UIAA-Skala)", "II")
    assert grade_matches("II(UIAA-Skala)", "II")
    assert not grade_matches("III (UIAA-Skala)", "II")


def test_split_grade() -> None:
    assert split_grade("T5- - anspruchsvolles Alpinwandern") == ("t5", "-")
    assert split_grade("ZS") == ("zs", "")
    assert split_grade(None) is None


# --- Suchbegriffe ----------------------------------------------------------


def test_grade_terms_are_cleaned_and_sorted() -> None:
    assert grade_terms(["ZS", "t4", " ", "T4", "ws+"]) == ["t4", "ws+", "zs"]
    assert grade_terms("ZS") == ["zs"]
    assert grade_terms(None) == []


@pytest.mark.parametrize(
    "good", ["T1", "t6", "L", "WS-", "ZS+", "S", "SS", "AS", "EX", "III", "IV+", "VI"]
)
def test_known_grades_are_accepted(good: str) -> None:
    assert is_grade(good)


@pytest.mark.parametrize("bad", ["alpinwandern", "6a", "T7", "Z"])
def test_anything_that_is_no_grade_is_rejected(bad: str) -> None:
    """Sonst faende ein Tippfehler still gar nichts."""
    assert not is_grade(bad)
    with pytest.raises(ValueError, match="keine Schwierigkeitsstufe"):
        grade_terms([bad])


# --- Tourtypen -------------------------------------------------------------


def test_tour_types_are_named_as_agreed() -> None:
    assert TOUR_TYPES == ("ski-hochtour", "alpinwandern-hochtour", "hochtour")


def test_ski_grade_makes_a_ski_hochtour_even_with_alpine_hiking() -> None:
    assert tour_type(None, "WS", "ZS") == "ski-hochtour"
    assert tour_type("T5 - anspruchsvolles Alpinwandern", "ZS", "S") == "ski-hochtour"


def test_t4_to_t6_without_ski_grade_makes_an_alpinwandern_hochtour() -> None:
    assert tour_type("T5- - anspruchsvolles Alpinwandern", "WS", None) == "alpinwandern-hochtour"
    assert tour_type("T6", "ZS", None) == "alpinwandern-hochtour"


def test_everything_else_with_alpine_grade_is_a_hochtour() -> None:
    assert tour_type("T3", "L", None) == "hochtour"
    assert tour_type(None, "ZS-", None) == "hochtour"


def test_no_alpine_grade_means_no_tour_type() -> None:
    assert tour_type("T5", None, "WS") is None
    assert tour_type("T4", None, None) is None


def test_scale_from_listing_title() -> None:
    assert scale_from_title("Hochtouren Schwierigkeit") == "hochtouren"
    assert scale_from_title("Wandern Schwierigkeit") == "wandern"
    assert scale_from_title("Ski Schwierigkeit") == "ski"
    assert scale_from_title("Mountainbike Schwierigkeit") == "mountainbike"
