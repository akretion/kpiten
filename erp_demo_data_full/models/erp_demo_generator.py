import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ErpDemoFull(models.Model):
    _inherit = "erp.demo.generator"

    def generate_full_demo_data(self):
        """Entry point of the erp_demo_data_full module (months=12)."""
        return self.generate_demo_data(months=12)
