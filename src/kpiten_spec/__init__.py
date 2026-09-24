"""The syntax of the KPI of KpiTen : its schema and the validation of a definition.

Standard library only, Python 3.8 and after : the Odoo module `kpiten` uses it to check
the tiles on every series, kpiten-core to read them.
"""

from kpiten_spec.validate import validate, validate_display, validate_toml  # noqa: F401
