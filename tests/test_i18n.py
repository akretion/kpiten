from kpiten_core import comparison, i18n
from kpiten_core.tiles import TileResult, rows_note


def test_a_french_user_reads_french_and_the_others_english():
    fr = i18n.translator("fr_BE")
    assert fr("Tile #{id} deleted", id=3) == "Tuile n°3 supprimée"
    assert fr("2026-04") == "2026-04"  # a month is not in the catalog
    assert i18n.translator("de_DE")("Panel") == "Panel"
    note = TileResult(kind="data", label="t", meta={"notes": [rows_note(500, 1200)]})
    assert note.note == "First 500 of 1\u202f200 rows"
    assert note.note_in(fr) == "500 premières lignes sur 1\u202f200"
    card = {
        "direction": "up",
        "text": "5.0%",
        "description": "since last period",
        "previous": "10",
        "period": None,
        "tone": "good",
    }
    assert "depuis la période précédente" in comparison.html_block(card, tr=fr)
