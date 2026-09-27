# the filters of a panel were JSON : written back as TOML (see `filter_config.py`) ; a
# value that is not JSON is left as it is
from odoo.addons.kpiten.filter_config import normalize


def migrate(cr, version):
    cr.execute("SELECT id, filter_config FROM kt_panel WHERE filter_config IS NOT NULL")
    for panel_id, text in cr.fetchall():
        toml = normalize(text)
        if toml != text:
            cr.execute(
                "UPDATE kt_panel SET filter_config = %s WHERE id = %s",
                (toml, panel_id),
            )
