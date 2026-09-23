# the themes Akretion and Midnight gave way to Capitaine, Akretion Sand is named Mixed
OLD_THEMES = {
    "akretion": "capitaine",
    "midnight": "capitaine",
    "akretion_sand": "mixed",
}


def migrate(cr, version):
    for old, new in OLD_THEMES.items():
        cr.execute(
            "UPDATE kt_config SET default_theme = %s WHERE default_theme = %s",
            (new, old),
        )
