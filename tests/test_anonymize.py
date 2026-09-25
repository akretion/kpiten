import polars as pl

from kpiten_core import anonymize

FIELDS = {
    "partner_id": {"type": "many2one", "rel": "res.partner"},
    "user_id": {"type": "many2one", "rel": "res.users"},
    "team_id": {"type": "many2one", "rel": "crm.team"},
    "product_id": {"type": "many2one", "rel": "product.product"},
    "email": {"type": "char"},
    "phone": {"type": "char"},
    "note": {"type": "html"},
    "state": {"type": "selection"},
}
FRAME = pl.DataFrame(
    {
        "partner_id": ["Dupont SA", "Martin & Fils", "Dupont SA", None],
        "partner_id_": [7, 8, 7, None],
        "user_id": ["Marie Stourne"] * 4,
        "team_id": ["Export"] * 4,
        "product_id": ["Ergo chair pro"] * 4,
        "product_id.categ_id.complete_name": ["All / Chairs"] * 4,
        "email": ["a@dupont.fr", "b@martin.fr", "a@dupont.fr", None],
        "phone": ["+33 6 12 34 56 78"] * 4,
        "note": ["<p>secret</p>"] * 4,
        "state": ["sale", "draft", "sale", "sale"],
        "amount": [10.0, 20.0, 30.0, 40.0],
    }
).lazy()


def test_the_summary_keeps_the_sense_and_hides_the_names():
    anon = anonymize.Anonymizer("sale.order", FIELDS)
    text = anonymize.summary(FRAME, anon)
    for real in ("Dupont", "Martin", "Marie", "Ergo", "Chairs", "dupont.fr", "+33"):
        assert real not in text
    for kept in ("Customer 1", "Salesperson 1", "Product 1", "Category 1 / Category 2"):
        assert kept in text
    assert "contact1@example.com" in text and "Export" in text  # a team : kept
    assert "note : String ; not sent" in text and "secret" not in text
    assert "from 10 to 40, mean 25" in text


def test_a_pseudonym_is_stable_and_revealed():
    anon = anonymize.Anonymizer("purchase.order", FIELDS)
    anonymize.summary(FRAME, anon)
    hidden = anon.hide("Orders of Dupont SA and Martin & Fils")
    assert hidden == "Orders of Supplier 1 and Supplier 2"  # the most frequent first
    assert anon.reveal(hidden) == "Orders of Dupont SA and Martin & Fils"
    assert anon.reveal("Supplier 99 is unknown") == "Supplier 99 is unknown"


def test_clear_sends_the_values_but_never_the_secrets():
    anon = anonymize.Anonymizer("sale.order", FIELDS, hide=False)
    text = anonymize.summary(FRAME, anon, "clear")
    assert "Dupont SA" in text and "Customer 1" not in text
    assert "+33" not in text and "secret" not in text


def test_the_schema_level_sends_the_columns_only():
    text = anonymize.summary(
        FRAME, anonymize.Anonymizer("sale.order", FIELDS), "schema"
    )
    assert (
        "- partner_id : String" in text
        and "Dupont" not in text
        and "Customer" not in text
    )
