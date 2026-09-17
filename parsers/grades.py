import re
from typing import Optional, Sequence


# Skalen, gegen die eine Stufe verglichen wird. Die Mountainbike Skala fuehrt
# das Projekt nicht, sie zaehlt bei keinem Vergleich.
GRADE_SCALES = ("wandern", "hochtouren", "klettern", "ski")

# Tourtypen fuer Touren mit Hochtourennote. Sie schliessen sich gegenseitig aus.
TOUR_TYPES = ("ski-hochtour", "alpinwandern-hochtour", "hochtour")

# Wanderstufen, die als Alpinwandern gelten.
ALPINE_HIKING_GRADES = ("t4", "t5", "t6")

# Erlaubte Suchbegriffe: T1 bis T6, die Hochtouren und Skiskala von L bis EX
# und roemische UIAA Grade, jeweils wahlweise mit + oder -.
GRADE_TERM = re.compile(r"^(t[1-6]|l|ws|zs|s|ss|as|ex|[ivx]+)[+-]?$", re.IGNORECASE)

# Die Stufe steht vorne, danach folgt je nach Quelle eine Beschreibung oder
# der Skalenname: "T4- - Alpinwandern", "III (UIAA-Skala)", "II(UIAA-Skala)".
LEADING_GRADE = re.compile(r"^\s*([A-Za-z0-9]+[+-]?)")


def split_grade(value: Optional[str]) -> Optional[tuple[str, str]]:
    """Aus "T4- - Alpinwandern" wird ("t4", "-"), aus "ZS" wird ("zs", "")."""
    if not value:
        return None
    match = LEADING_GRADE.match(value)
    if not match:
        return None
    token = match.group(1).lower()
    base = token.rstrip("+-")
    return base, token[len(base):]


def grade_matches(value: Optional[str], term: str) -> bool:
    """
    Vergleicht eine Stufe exakt statt als Teiltext.

    ZS trifft ZS-, ZS und ZS+, ZS+ trifft nur ZS+. S trifft nicht WS oder
    ZS, II trifft nicht III. Bei einem Teiltextvergleich steckte S in fast
    jeder Hochtourennote und II in jeder III.
    """
    grade = split_grade(value)
    wanted = split_grade(term)
    if grade is None or wanted is None or grade[0] != wanted[0]:
        return False
    return not wanted[1] or grade[1] == wanted[1]


def is_grade(term: str) -> bool:
    return bool(GRADE_TERM.match(str(term).strip()))


def grade_terms(schwierigkeit: str | Sequence[str] | None) -> list[str]:
    """
    Bereinigt gesuchte Stufen: klein geschrieben, sortiert, ohne leere und
    doppelte Eintraege.

    Ein einzelner String wird nicht Zeichen fuer Zeichen gelesen. Etwas, das
    keine Stufe ist, loest einen ValueError aus, statt still nichts zu finden.
    """
    if schwierigkeit is None:
        return []
    if isinstance(schwierigkeit, str):
        schwierigkeit = [schwierigkeit]

    terms: list[str] = []
    for raw in schwierigkeit:
        term = str(raw).strip().lower()
        if not term:
            continue
        if not is_grade(term):
            raise ValueError(
                f"{raw!r} ist keine Schwierigkeitsstufe. Erlaubt sind etwa T4, WS, ZS+, S oder III"
            )
        terms.append(term)
    return sorted(dict.fromkeys(terms))


def tour_type(
    hiking: Optional[str], alpine: Optional[str], ski: Optional[str]
) -> Optional[str]:
    """
    Ordnet eine Tour mit Hochtourennote einem Typ zu, ohne Hochtourennote gibt
    es keinen.

    Die Skinote geht vor: Eine Skitour mit Hochtourennote bleibt ski-hochtour,
    auch wenn der Zustieg eine T Note traegt. Eine Wandernote T4 bis T6 macht
    ohne Skinote eine alpinwandern-hochtour, alles uebrige ist hochtour.
    """
    if split_grade(alpine) is None:
        return None
    if split_grade(ski) is not None:
        return "ski-hochtour"
    if any(grade_matches(hiking, grade) for grade in ALPINE_HIKING_GRADES):
        return "alpinwandern-hochtour"
    return "hochtour"


def scale_from_title(title: str) -> str:
    """Aus "Hochtouren Schwierigkeit" auf der Listenseite wird hochtouren."""
    return re.sub(r"\s*schwierigkeit\s*$", "", title.strip(), flags=re.IGNORECASE).lower()
