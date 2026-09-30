"""The customer invoices of the big sales : one posted invoice per invoiced
order (its lines, one tax line per tax, the receivable), not paid. Inserted in
SQL, cloned from draft invoices made through the ORM from the template orders
(accounts, taxes, tags, fiscal position and payment terms of the zone), like the
orders ; the amounts are the ones of the order, in the company currency at the
rate of the order."""

from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from odoo import models
from odoo.exceptions import UserError

from .erp_demo_generator import SILENT, _cents

INVOICE_TEMP = """
CREATE TEMP TABLE _kt_big_inv (
    inv_id int, order_id int, tpl_inv_id int, name varchar, prefix varchar,
    seq_no int, origin varchar, date date, due date, delivery_date date,
    partner_id int, user_id int, team_id int, medium_id int, source_id int,
    rate numeric, untaxed numeric, tax numeric, total numeric,
    untaxed_c numeric, tax_c numeric, total_c numeric
)
"""
INVOICE_LINE_TEMP = """
CREATE TEMP TABLE _kt_big_aml (
    aml_id int, inv_id int, tpl_aml_id int, line_id int, seq int, name varchar,
    qty numeric, price_unit numeric, subtotal numeric, total numeric,
    amount_currency numeric, balance numeric, tax_base numeric,
    residual numeric, residual_currency numeric, maturity date
)
"""


def _company_cents(cents, rate):
    """An amount of the order currency (cents) in the company currency (cents)."""
    return int((Decimal(cents) / rate).to_integral_value(ROUND_HALF_UP))


class ErpDemoBigInvoice(models.Model):
    _inherit = "erp.demo.generator"

    # ---- templates ----------------------------------------------------------
    def _big_invoice_templates(self, orders):
        """Draft invoices of the confirmed template orders of a zone, the rows the
        invoices are cloned from : {"invoices": records, "invoice": id,
        "products": {product id: line id}, "taxes": {product id: tax line id or
        None}, "receivable": line id, "due_days": int, "journal": id, "code": str}.
        """
        vals = []
        for order in orders:
            invoice = order._prepare_invoice()
            invoice["invoice_line_ids"] = [
                (0, 0, line._prepare_invoice_line(quantity=1))
                for line in order.order_line
            ]
            vals.append(invoice)
        invoices = self.env["account.move"].with_context(**SILENT).create(vals)
        self.env.flush_all()
        products, taxes, receivable = {}, {}, None
        for invoice in invoices:
            tax_lines = invoice.line_ids.filtered("tax_line_id")
            for line in invoice.invoice_line_ids.filtered("product_id"):
                pid = line.product_id.id
                if pid in products:
                    continue
                if len(line.tax_ids) > 1:
                    raise UserError(
                        f"{line.product_id.display_name} : one tax per product only."
                    )
                found = tax_lines.filtered(lambda t: t.tax_line_id == line.tax_ids)
                if len(found) > 1 or (line.tax_ids.amount and not found):
                    raise UserError(
                        f"Unsupported tax '{line.tax_ids.display_name}' on "
                        f"{line.product_id.display_name} : one tax line per tax only."
                    )
                products[pid] = line.id
                taxes[pid] = found.id or None
            receivable = receivable or invoice.line_ids.filtered(
                lambda line: line.display_type == "payment_term"
            )
        if len(receivable) != 1:
            raise UserError("Only payment terms of one installment are supported.")
        first = invoices[0]
        return {
            "invoices": invoices,
            "invoice": first.id,
            "products": products,
            "taxes": taxes,
            "receivable": receivable.id,
            "due_days": (receivable.date_maturity - first.date).days,
            "journal": first.journal_id.id,
            "code": first.journal_id.code,
        }

    def _big_invoice_numbers(self, journal_id, prefixes):
        """{prefix: last number used} of the invoices of a journal."""
        self.env.cr.execute(
            "SELECT sequence_prefix, max(sequence_number) FROM account_move "
            "WHERE journal_id = %s AND sequence_prefix = ANY(%s) GROUP BY 1",
            (journal_id, list(prefixes)),
        )
        return dict(self.env.cr.fetchall())

    # ---- one batch ----------------------------------------------------------
    def _big_invoice_rows(self, orders, ctx):
        """The invoices of the invoiced orders of a batch and their lines ; their
        ids and names (in the order of the invoice dates) are reserved here."""
        invoiced = sorted(
            (o for o in orders if o["invoice_date"]), key=lambda o: o["invoice_date"]
        )
        if not invoiced:
            return [], []
        # the tax lines of each order : one per template tax line of its products
        n_lines = 0
        for order in invoiced:
            taxes = order["z"]["invoice"]["taxes"]
            keys = {taxes[ctx["pids"][line[0]]] for line in order["lines"]}
            n_lines += len(order["lines"]) + len(keys - {None}) + 1
        first_inv = self._big_reserve("account_move_id_seq", len(invoiced))
        first_aml = self._big_reserve("account_move_line_id_seq", n_lines)
        journals = {}
        for order in invoiced:
            tpl = order["z"]["invoice"]
            prefix = f"{tpl['code']}/{order['invoice_date'].year}/"
            journals.setdefault(tpl["journal"], set()).add(prefix)
        last = {}
        for journal_id, prefixes in journals.items():
            for prefix, number in self._big_invoice_numbers(
                journal_id, prefixes
            ).items():
                last[(journal_id, prefix)] = number

        invoices, lines = [], []
        aml_id = first_aml
        for i, order in enumerate(invoiced):
            tpl = order["z"]["invoice"]
            inv_id = first_inv + i
            inv_date = order["invoice_date"]
            prefix = f"{tpl['code']}/{inv_date.year}/"
            key = (tpl["journal"], prefix)
            last[key] = last.get(key, 0) + 1
            name = f"{prefix}{last[key]:05d}"
            rate = Decimal(str(order["rate"]))
            untaxed = tax = untaxed_c = tax_c = 0
            by_tax = {}  # template tax line -> [tax, base in company currency]
            for k, (index, qty, price, subtotal, line_tax) in enumerate(order["lines"]):
                pid = ctx["pids"][index]
                balance = _company_cents(subtotal, rate)
                untaxed += subtotal
                untaxed_c += balance
                tax += line_tax
                lines.append(
                    (
                        aml_id,
                        inv_id,
                        tpl["products"][pid],
                        order["line_ids"][k],
                        10 + k,
                        None,
                        qty,
                        _cents(price),
                        _cents(subtotal),
                        _cents(subtotal + line_tax),
                        -_cents(subtotal),
                        -_cents(balance),
                        0,
                        0,
                        0,
                        None,
                    )
                )
                aml_id += 1
                tax_line = tpl["taxes"][pid]
                if tax_line:
                    group = by_tax.setdefault(tax_line, [0, 0])
                    group[0] += line_tax
                    group[1] += balance
            for tax_line, (amount, base) in by_tax.items():
                balance = _company_cents(amount, rate)
                tax_c += balance
                lines.append(
                    (
                        aml_id,
                        inv_id,
                        tax_line,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        None,
                        -_cents(amount),
                        -_cents(balance),
                        _cents(base),
                        0,
                        0,
                        None,
                    )
                )
                aml_id += 1
            total, total_c = untaxed + tax, untaxed_c + tax_c
            lines.append(
                (
                    aml_id,
                    inv_id,
                    tpl["receivable"],
                    None,
                    None,
                    name,
                    None,
                    None,
                    None,
                    None,
                    _cents(total),
                    _cents(total_c),
                    0,
                    _cents(total_c),
                    _cents(total),
                    inv_date + timedelta(days=tpl["due_days"]),
                )
            )
            aml_id += 1
            invoices.append(
                (
                    inv_id,
                    order["id"],
                    tpl["invoice"],
                    name,
                    prefix,
                    last[key],
                    order["name"],
                    inv_date,
                    inv_date + timedelta(days=tpl["due_days"]),
                    order["plan"]["effective_date"].date(),
                    order["partner_id"],
                    order["user_id"],
                    order["z"]["team"],
                    order["medium_id"],
                    order["source_id"],
                    rate,
                    _cents(untaxed),
                    _cents(tax),
                    _cents(total),
                    _cents(untaxed_c),
                    _cents(tax_c),
                    _cents(total_c),
                )
            )
        return invoices, lines

    def _big_invoice_insert(self, invoices, lines):
        cr = self.env.cr
        if not invoices:
            return
        cr.execute(INVOICE_TEMP)
        cr.execute(INVOICE_LINE_TEMP)
        cr.execute_values("INSERT INTO _kt_big_inv VALUES %s", invoices, page_size=2000)
        cr.execute_values("INSERT INTO _kt_big_aml VALUES %s", lines, page_size=2000)

        columns = set(self._big_columns("account_move"))
        created = "i.date::timestamp"
        move_values = {
            "id": "i.inv_id",
            "name": "i.name",
            "sequence_prefix": "i.prefix",
            "sequence_number": "i.seq_no",
            "state": "'posted'",
            "date": "i.date",
            "invoice_date": "i.date",
            "invoice_date_due": "i.due",
            "delivery_date": "i.delivery_date",
            "partner_id": "i.partner_id",
            "commercial_partner_id": "coalesce(rp.commercial_partner_id, rp.id)",
            "partner_shipping_id": "i.partner_id",
            "invoice_partner_display_name": "rp.name",
            "invoice_origin": "i.origin",
            "payment_reference": "i.name",
            "invoice_user_id": "i.user_id",
            "team_id": "i.team_id",
            "medium_id": "i.medium_id",
            "source_id": "i.source_id",
            "invoice_currency_rate": "i.rate",
            "amount_untaxed": "i.untaxed",
            "amount_tax": "i.tax",
            "amount_total": "i.total",
            "amount_residual": "i.total",
            "amount_untaxed_signed": "i.untaxed_c",
            "amount_untaxed_in_currency_signed": "i.untaxed",
            "amount_tax_signed": "i.tax_c",
            "amount_total_signed": "i.total_c",
            "amount_total_in_currency_signed": "i.total",
            "amount_residual_signed": "i.total_c",
            "payment_state": "'not_paid'",
            "posted_before": "true",
            "checked": "true",
            "made_sequence_gap": "false",
            "is_move_sent": "false",
            "access_token": "NULL",
            "create_date": created,
            "write_date": created,
        }
        self._big_clone(
            "account_move",
            {c: e for c, e in move_values.items() if c in columns},
            "_kt_big_inv i JOIN account_move t ON t.id = i.tpl_inv_id "
            "JOIN res_partner rp ON rp.id = i.partner_id",
        )

        columns = set(self._big_columns("account_move_line"))
        line_values = {
            "id": "a.aml_id",
            "move_id": "a.inv_id",
            "move_name": "i.name",
            "parent_state": "'posted'",
            "date": "i.date",
            "invoice_date": "i.date",
            "partner_id": "i.partner_id",
            "sequence": "coalesce(a.seq, t.sequence)",
            "name": "coalesce(a.name, t.name)",
            "quantity": "coalesce(a.qty, t.quantity)",
            "price_unit": "coalesce(a.price_unit, t.price_unit)",
            "price_subtotal": "coalesce(a.subtotal, t.price_subtotal)",
            "price_total": "coalesce(a.total, t.price_total)",
            "amount_currency": "a.amount_currency",
            "balance": "a.balance",
            "debit": "greatest(a.balance, 0)",
            "credit": "greatest(-a.balance, 0)",
            "tax_base_amount": "a.tax_base",
            "amount_residual": "a.residual",
            "amount_residual_currency": "a.residual_currency",
            "date_maturity": "a.maturity",
            "discount": "0",
            "reconciled": "false",
            "matching_number": "NULL",
            "full_reconcile_id": "NULL",
            "create_date": created,
            "write_date": created,
        }
        self._big_clone(
            "account_move_line",
            {c: e for c, e in line_values.items() if c in columns},
            "_kt_big_aml a JOIN _kt_big_inv i ON i.inv_id = a.inv_id "
            "JOIN account_move_line t ON t.id = a.tpl_aml_id",
        )

        # the many2many of the lines : taxes and tax tags of the template line,
        # and the order line it invoices
        line_model = self.env["account.move.line"]
        for name in ("tax_ids", "tax_tag_ids"):
            field = line_model._fields[name]
            cr.execute(
                f'INSERT INTO "{field.relation}" ("{field.column1}", "{field.column2}") '
                f'SELECT a.aml_id, r."{field.column2}" FROM _kt_big_aml a '
                f'JOIN "{field.relation}" r ON r."{field.column1}" = a.tpl_aml_id'
            )
        field = self.env["sale.order.line"]._fields["invoice_lines"]
        cr.execute(
            f'INSERT INTO "{field.relation}" ("{field.column1}", "{field.column2}") '
            "SELECT a.line_id, a.aml_id FROM _kt_big_aml a WHERE a.line_id IS NOT NULL"
        )

        # every inserted invoice must be balanced
        cr.execute(
            "SELECT count(*) FROM (SELECT a.inv_id FROM _kt_big_aml a "
            "GROUP BY 1 HAVING abs(sum(a.balance)) > 0.001) unbalanced"
        )
        if cr.fetchone()[0]:
            raise UserError("Inserted invoices are not balanced.")
        cr.execute("DROP TABLE _kt_big_aml, _kt_big_inv")
