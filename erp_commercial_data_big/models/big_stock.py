"""The deliveries of the big sales : a picking per confirmed order (two for a
partial delivery : the delivered lines, then the backorder of the others), its
moves and move lines, the valuation layers of what is delivered, the monthly
inventory adjustments that bring the stock the deliveries take, and the quants
rebuilt from all of it. Inserted in SQL, cloned from template pickings made
through the ORM, like the orders."""

import random
from datetime import date, datetime

from odoo import models
from odoo.exceptions import UserError

from .erp_demo_generator import SILENT

INVENTORY_ORIGIN = "kpiten big demo inventory"  # stock.move.origin of the adjustments
INVENTORY_NAME = "Product Quantity Updated"  # what Odoo names an adjustment move
TEMPLATE_STOCK = 1000  # the quantity given to the templates, to get them reserved

PICKING_TEMP = """
CREATE TEMP TABLE _kt_big_picking (
    picking_id int, order_id int, name varchar, origin varchar, state varchar,
    backorder_id int, group_id int, partner_id int, tpl_picking_id int,
    date timestamp, scheduled_date timestamp, date_done timestamp,
    create_date timestamp
)
"""
MOVE_TEMP = """
CREATE TEMP TABLE _kt_big_move (
    move_id int, picking_id int, group_id int, partner_id int, line_id int,
    line_no int, product_id int, tpl_move_id int, tpl_move_line_id int,
    state varchar, reference varchar, origin varchar, qty numeric,
    date timestamp, date_deadline timestamp, create_date timestamp,
    storable boolean, categ_id int, unit_cost numeric, description varchar
)
"""
INVENTORY_TEMP = """
CREATE TEMP TABLE _kt_big_inventory (
    move_id int, product_id int, tpl_move_id int, tpl_move_line_id int,
    qty numeric, date timestamp, categ_id int, unit_cost numeric,
    description varchar
)
"""


class ErpDemoBigStock(models.Model):
    _inherit = "erp.demo.generator"

    # ---- products and locations ---------------------------------------------
    def _big_storable_vals(self, storable):
        """The values of a product tracked in stock (`is_storable` from Odoo 18, the
        type `product` before), or of a plain consumable."""
        if "is_storable" in self.env["product.template"]._fields:
            return {"type": "consu", "is_storable": storable}
        return {"type": "product" if storable else "consu"}

    def _big_is_storable(self, product):
        if "is_storable" in product._fields:
            return product.is_storable
        return product.type == "product"

    def _big_stock_location(self):
        warehouse = self.env["stock.warehouse"].search(
            [("company_id", "=", self.env.company.id)], limit=1
        )
        return warehouse.lot_stock_id

    # ---- templates ----------------------------------------------------------
    def _big_stock_give(self, products):
        """Stock for the templates of the storable products, so that their
        pickings are reserved (and have move lines) : the quants are rebuilt from
        the moves at the end (`_big_stock_finish`)."""
        location = self._big_stock_location()
        quant = self.env["stock.quant"]
        for product in products:
            if self._big_is_storable(product):
                quant._update_available_quantity(product, location, TEMPLATE_STOCK)

    def _big_stock_templates(self, orders, products):
        """The rows the pickings are cloned from, taken from the confirmed template
        orders of a zone : {"picking": id, "moves": {product id: move id},
        "move_line": id}."""
        pickings = orders.picking_ids
        moves = {}
        for move in pickings.move_ids:
            moves.setdefault(move.product_id.id, move.id)
        missing = [p.display_name for p in products if p.id not in moves]
        move_line = pickings.move_line_ids[:1]
        if missing or not move_line:
            raise UserError(
                "The template orders got no reserved picking for : "
                f"{', '.join(missing) or 'any product'}."
            )
        return {"picking": pickings[0].id, "moves": moves, "move_line": move_line.id}

    def _big_stock_sequence(self, picking_id):
        """(postgres sequence, prefix, padding) of the names of the delivery orders."""
        picking = self.env["stock.picking"].browse(picking_id)
        sequence = picking.picking_type_id.sequence_id
        prefix = sequence.prefix or ""
        if (
            sequence.implementation != "standard"
            or sequence.use_date_range
            or sequence.number_increment != 1
            or sequence.suffix
            or "%" in prefix
        ):
            raise UserError("The delivery sequence must be a plain 'standard' one.")
        return f"ir_sequence_{sequence.id:03d}", prefix, sequence.padding

    # ---- one batch ----------------------------------------------------------
    def _big_stock_rows(self, orders, ctx):
        """The procurement groups, pickings and moves of the confirmed orders of a
        batch (`orders` : the planned orders, with their ids and lines) ; their
        ids and names are reserved here."""
        confirmed = [o for o in orders if o["pickings"]]
        n_pickings = sum(len(o["pickings"]) for o in confirmed)
        n_moves = sum(len(ks) for o in confirmed for _s, ks in o["pickings"])
        first_group = self._big_reserve("procurement_group_id_seq", len(confirmed))
        first_picking = self._big_reserve("stock_picking_id_seq", n_pickings)
        first_move = self._big_reserve("stock_move_id_seq", n_moves)
        sequence, prefix, padding = ctx["picking_sequence"]
        first_number = self._big_reserve(sequence, n_pickings)
        groups, pickings, moves = [], [], []
        picking_id, move_id = first_picking, first_move
        for i, order in enumerate(confirmed):
            plan, z = order["plan"], order["z"]
            group_id = first_group + i
            order["group_id"] = group_id
            groups.append(
                (
                    group_id,
                    order["name"],
                    order["partner_id"],
                    order["id"],
                    plan["create_date"],
                )
            )
            first_of_order = picking_id
            for state, line_numbers in order["pickings"]:
                name = f"{prefix}{str(first_number + picking_id - first_picking).zfill(padding)}"
                done = state == "done"
                pickings.append(
                    (
                        picking_id,
                        order["id"],
                        name,
                        order["name"],
                        state,
                        first_of_order if picking_id != first_of_order else None,
                        group_id,
                        order["partner_id"],
                        z["stock"]["picking"],
                        plan["create_date"],
                        plan["commitment_date"],
                        plan["effective_date"] if done else None,
                        plan["create_date"],
                    )
                )
                for k in line_numbers:
                    index, qty = order["lines"][k][0], order["lines"][k][1]
                    moves.append(
                        (
                            move_id,
                            picking_id,
                            group_id,
                            order["partner_id"],
                            order["line_ids"][k],
                            k + 1,
                            ctx["pids"][index],
                            z["stock"]["moves"][ctx["pids"][index]],
                            z["stock"]["move_line"],
                            state,
                            name,
                            order["name"],
                            qty,
                            plan["effective_date"] if done else plan["commitment_date"],
                            plan["commitment_date"],
                            plan["create_date"],
                            ctx["storable"][index],
                            ctx["categs"][index],
                            ctx["costs"][index],
                            f"{name} - {ctx['names'][index]}",
                        )
                    )
                    move_id += 1
                picking_id += 1
        return groups, pickings, moves

    def _big_groups_insert(self, groups):
        """The procurement groups (one per confirmed order, what links its pickings
        to it), before the orders that point to them ; their order is set by
        `_big_stock_insert`."""
        if not groups:
            return
        uid = self.env.uid
        columns = set(self._big_columns("procurement_group"))
        names = ["id", "name", "partner_id", "move_type"]
        names += ["create_uid", "write_uid", "create_date", "write_date"]
        keep = [i for i, name in enumerate(names) if name in columns]
        self.env.cr.execute_values(
            f'INSERT INTO procurement_group ({", ".join(names[i] for i in keep)}) '
            "VALUES %s",
            [
                tuple(row[i] for i in keep)
                for row in (
                    (gid, name, partner, "direct", uid, uid, created, created)
                    for gid, name, partner, _order, created in groups
                )
            ],
            page_size=2000,
        )

    def _big_stock_insert(self, groups, pickings, moves):
        """Insert what `_big_stock_rows` planned (the orders are already in)."""
        cr = self.env.cr
        if not pickings:
            return
        cr.execute(PICKING_TEMP)
        cr.execute(MOVE_TEMP)
        cr.execute_values(
            "INSERT INTO _kt_big_picking VALUES %s", pickings, page_size=2000
        )
        cr.execute_values("INSERT INTO _kt_big_move VALUES %s", moves, page_size=2000)
        if "sale_id" in self._big_columns("procurement_group"):
            # the orders are in now : each group points back to its order
            cr.execute(
                "UPDATE procurement_group g SET sale_id = p.order_id "
                "FROM _kt_big_picking p WHERE p.group_id = g.id"
            )

        columns = set(self._big_columns("stock_picking"))
        picking_values = {
            "id": "p.picking_id",
            "name": "p.name",
            "origin": "p.origin",
            "state": "p.state",
            "backorder_id": "p.backorder_id",
            "group_id": "p.group_id",
            "partner_id": "p.partner_id",
            "sale_id": "p.order_id",
            "date": "p.date",
            "scheduled_date": "p.scheduled_date",
            "date_deadline": "p.scheduled_date",
            "date_done": "p.date_done",
            "printed": "false",
            "create_date": "p.create_date",
            "write_date": "coalesce(p.date_done, p.create_date)",
        }
        self._big_clone(
            "stock_picking",
            {c: e for c, e in picking_values.items() if c in columns},
            "_kt_big_picking p JOIN stock_picking t ON t.id = p.tpl_picking_id",
        )

        columns = set(self._big_columns("stock_move"))
        done = "m.state = 'done'"
        move_values = {
            "id": "m.move_id",
            "picking_id": "m.picking_id",
            "group_id": "m.group_id",
            "partner_id": "m.partner_id",
            "sale_line_id": "m.line_id",
            "sequence": "10 + m.line_no",
            "state": "m.state",
            "reference": "m.reference",
            "origin": "m.origin",
            "product_qty": "m.qty",
            "product_uom_qty": "m.qty",
            "quantity": "m.qty",
            "picked": done,
            "date": "m.date",
            "date_deadline": "m.date_deadline",
            "reservation_date": f"CASE WHEN {done} THEN NULL ELSE m.create_date::date END",
            "create_date": "m.create_date",
            "write_date": "m.date",
        }
        self._big_clone(
            "stock_move",
            {c: e for c, e in move_values.items() if c in columns},
            "_kt_big_move m JOIN stock_move t ON t.id = m.tpl_move_id",
        )
        self._big_clone_move_lines(
            "_kt_big_move m JOIN stock_move tm ON tm.id = m.tpl_move_id "
            "JOIN stock_move_line t ON t.id = m.tpl_move_line_id",
            {
                "picking_id": "m.picking_id",
                "state": "m.state",
                "reference": "m.reference",
                "picked": done,
                "location_id": "tm.location_id",
                "location_dest_id": "tm.location_dest_id",
            },
        )
        self._big_valuation("_kt_big_move m", "m.state = 'done' AND m.storable", -1)
        cr.execute("DROP TABLE _kt_big_move, _kt_big_picking")

    def _big_clone_move_lines(self, source, overrides):
        """A move line per move of `source` (aliased `m`, with the template move line
        `t`), its whole quantity."""
        columns = set(self._big_columns("stock_move_line"))
        values = {
            "move_id": "m.move_id",
            "product_id": "m.product_id",
            "product_uom_id": "tm.product_uom",
            "quantity": "m.qty",
            "quantity_product_uom": "m.qty",
            "description_picking": "tm.description_picking",
            "date": "m.date",
            "create_date": "m.create_date",
            "write_date": "m.date",
            **overrides,
        }
        values = {c: e for c, e in values.items() if c in columns}
        values["id"] = "nextval('stock_move_line_id_seq')"
        self._big_clone("stock_move_line", values, source)

    def _big_valuation(self, source, where, sign):
        """The valuation layers (standard cost) of the done moves of `source`
        (aliased `m`, with qty, unit_cost, categ_id, description) : `sign` -1 for
        what leaves the stock, 1 for what comes in (then still in stock)."""
        if "stock.valuation.layer" not in self.env:
            return
        cr = self.env.cr
        remaining = "m.qty" if sign > 0 else "0"
        cr.execute(
            f"""
            INSERT INTO stock_valuation_layer (
                company_id, product_id, categ_id, stock_move_id, description,
                quantity, unit_cost, value, remaining_qty, remaining_value,
                create_uid, write_uid, create_date, write_date)
            SELECT %s, m.product_id, m.categ_id, m.move_id, m.description,
                   {sign} * m.qty, m.unit_cost, round({sign} * m.qty * m.unit_cost, 2),
                   {remaining}, round({remaining} * m.unit_cost, 2),
                   %s, %s, m.date, m.date
            FROM {source} WHERE {where}
            """,
            (self.env.company.id, self.env.uid, self.env.uid),
        )

    # ---- after the batches --------------------------------------------------
    def _big_stock_finish(self, ctx):
        """The stock the deliveries took : an inventory adjustment per storable
        product at the start of each month, of what that month delivered (the
        first also brings a safety stock, the current one what the open pickings
        reserve) ; then the quants, rebuilt from the moves. Replaces the
        adjustments of an earlier run."""
        cr = self.env.cr
        storable = [pid for pid, s in zip(ctx["pids"], ctx["storable"]) if s]
        if not storable:
            return
        stock, customer = ctx["stock_location"], ctx["customer_location"]
        cr.execute("SELECT id FROM stock_move WHERE origin = %s", (INVENTORY_ORIGIN,))
        old = [row[0] for row in cr.fetchall()]
        if old:
            if "stock.valuation.layer" in self.env:
                cr.execute(
                    "DELETE FROM stock_valuation_layer WHERE stock_move_id = ANY(%s)",
                    (old,),
                )
            cr.execute("DELETE FROM stock_move_line WHERE move_id = ANY(%s)", (old,))
            cr.execute("DELETE FROM stock_move WHERE id = ANY(%s)", (old,))

        cr.execute(
            """
            SELECT product_id, date_trunc('month', date), sum(quantity)
            FROM stock_move WHERE state = 'done' AND location_id = %s
              AND location_dest_id = %s AND product_id = ANY(%s)
            GROUP BY 1, 2
            """,
            (stock, customer, storable),
        )
        need = {}
        for product_id, month, qty in cr.fetchall():
            need.setdefault(product_id, {})[month] = qty
        cr.execute(
            """
            SELECT product_id, sum(quantity) FROM stock_move
            WHERE state IN ('assigned', 'partially_available') AND location_id = %s
              AND product_id = ANY(%s)
            GROUP BY 1
            """,
            (stock, storable),
        )
        this_month = datetime.combine(date.today().replace(day=1), datetime.min.time())
        for product_id, qty in cr.fetchall():
            months = need.setdefault(product_id, {})
            months[this_month] = months.get(this_month, 0) + qty

        index_of = {pid: i for i, pid in enumerate(ctx["pids"])}
        rows = []
        for product_id, months in need.items():
            first = min(months)
            months[first] += random.Random(product_id).randint(10, 60)  # safety
            i = index_of[product_id]
            for month, qty in sorted(months.items()):
                rows.append(
                    (
                        product_id,
                        ctx["inventory_moves"][product_id],
                        ctx["inventory_move_line"],
                        qty,
                        month,
                        ctx["categs"][i],
                        ctx["costs"][i],
                        f"{INVENTORY_NAME} - {ctx['names'][i]}",
                    )
                )
        first_move = self._big_reserve("stock_move_id_seq", len(rows))
        cr.execute(INVENTORY_TEMP)
        cr.execute_values(
            "INSERT INTO _kt_big_inventory VALUES %s",
            [(first_move + n, *row) for n, row in enumerate(rows)],
            page_size=2000,
        )
        columns = set(self._big_columns("stock_move"))
        inventory = ctx["inventory_location"]
        values = {
            "id": "m.move_id",
            "name": f"'{INVENTORY_NAME}'",
            "reference": f"'{INVENTORY_NAME}'",
            "origin": f"'{INVENTORY_ORIGIN}'",
            "is_inventory": "true",
            "location_id": str(inventory),
            "location_dest_id": str(stock),
            "location_final_id": "NULL",
            "picking_id": "NULL",
            "picking_type_id": "NULL",
            "group_id": "NULL",
            "rule_id": "NULL",
            "sale_line_id": "NULL",
            "partner_id": "NULL",
            "warehouse_id": "NULL",
            "description_picking": "NULL",
            "sequence": "10",
            "state": "'done'",
            "product_qty": "m.qty",
            "product_uom_qty": "m.qty",
            "quantity": "m.qty",
            "picked": "true",
            "date": "m.date",
            "date_deadline": "NULL",
            "reservation_date": "NULL",
            "create_date": "m.date",
            "write_date": "m.date",
        }
        self._big_clone(
            "stock_move",
            {c: e for c, e in values.items() if c in columns},
            "_kt_big_inventory m JOIN stock_move t ON t.id = m.tpl_move_id",
        )
        self._big_clone_move_lines(
            "_kt_big_inventory m JOIN stock_move tm ON tm.id = m.tpl_move_id "
            "JOIN stock_move_line t ON t.id = m.tpl_move_line_id",
            {
                "picking_id": "NULL",
                "state": "'done'",
                "reference": f"'{INVENTORY_NAME}'",
                "picked": "true",
                "location_id": str(inventory),
                "location_dest_id": str(stock),
                "description_picking": "NULL",
                "create_date": "m.date",
            },
        )
        self._big_valuation("_kt_big_inventory m", "true", 1)
        cr.execute("DROP TABLE _kt_big_inventory")

    def _big_stock_finish_quants(self, ctx):
        """The quants of the storable products, once the templates are gone."""
        storable = [pid for pid, s in zip(ctx["pids"], ctx["storable"]) if s]
        if storable:
            self._big_rebuild_quants(storable)

    def _big_rebuild_quants(self, product_ids):
        """The quants of `product_ids`, from their done move lines (a quant in every
        location, as Odoo keeps them), reserved by their open move lines."""
        cr = self.env.cr
        columns = set(self._big_columns("stock_move_line"))
        qty = (
            "quantity_product_uom" if "quantity_product_uom" in columns else "quantity"
        )
        cr.execute("DELETE FROM stock_quant WHERE product_id = ANY(%s)", (product_ids,))
        quant_columns = set(self._big_columns("stock_quant"))
        inventory_date = date(date.today().year, 12, 31)
        values = {
            "product_id": "q.product_id",
            "location_id": "q.location_id",
            "company_id": "l.company_id",
            "quantity": "q.quantity",
            "reserved_quantity": "q.reserved",
            "inventory_quantity": "0",
            "inventory_diff_quantity": "-q.quantity",
            "inventory_quantity_set": "false",
            "inventory_date": (
                f"CASE WHEN l.usage = 'internal' THEN '{inventory_date}'::date END"
            ),
            "in_date": "q.in_date",
            "create_uid": str(self.env.uid),
            "write_uid": str(self.env.uid),
            "create_date": "q.in_date",
            "write_date": "now() at time zone 'UTC'",
        }
        values = {c: e for c, e in values.items() if c in quant_columns}
        cr.execute(
            f"""
            WITH moved AS (
                SELECT product_id, location_dest_id AS location_id, {qty} AS qty,
                       0 AS reserved, date FROM stock_move_line
                WHERE state = 'done' AND product_id = ANY(%s)
                UNION ALL
                SELECT product_id, location_id, -{qty}, 0, date FROM stock_move_line
                WHERE state = 'done' AND product_id = ANY(%s)
                UNION ALL
                SELECT product_id, location_id, 0, {qty}, date FROM stock_move_line
                WHERE state IN ('assigned', 'partially_available')
                  AND product_id = ANY(%s)
            ), q AS (
                SELECT product_id, location_id, sum(qty) AS quantity,
                       sum(reserved) AS reserved, max(date) AS in_date
                FROM moved GROUP BY 1, 2
                HAVING sum(qty) <> 0 OR sum(reserved) <> 0
            )
            INSERT INTO stock_quant ({", ".join(values)})
            SELECT {", ".join(values.values())}
            FROM q JOIN stock_location l ON l.id = q.location_id
            """,
            (product_ids, product_ids, product_ids),
        )

    def _big_cleanup_templates(self, orders):
        """Drop the template orders (confirmed : their pickings and draft invoices
        too)."""
        orders = orders.with_context(**SILENT)
        orders.invoice_ids.filtered(lambda move: move.state == "draft").unlink()
        pickings = orders.picking_ids
        groups = pickings.group_id if "group_id" in pickings._fields else None
        confirmed = orders.filtered(lambda o: o.state not in ("draft", "cancel"))
        if confirmed:
            confirmed._action_cancel()
        pickings.filtered(lambda p: p.state != "cancel").action_cancel()
        pickings.unlink()
        orders.unlink()
        if groups:
            groups.exists().unlink()
