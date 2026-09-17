# -*- coding: utf-8 -*-
from odoo import fields, models


class PolarsPivotColumn(models.TransientModel):
    """One row per column of the extracted Parquet sample. Backs the
    Index/Column/Value dropdowns of the wizard with a classic Many2one."""

    _name = "polars.pivot.column"
    _description = "Polars Pivot Sample Column"

    name = fields.Char(string="Column", required=True)
    type = fields.Char(string="Column Type")
    wizard_id = fields.Many2one(
        "polars.pivot.code.wizard",
        string="Wizard",
        ondelete="cascade",
        required=True,
    )
