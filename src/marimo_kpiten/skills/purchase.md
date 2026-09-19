---
name: purchase
description: Vocabulary of the Odoo purchase tables
tables: purchase.order, purchase.order.line
---
## Purchase vocabulary (Odoo)
- buyer, purchaser, purchase representative, "who orders" : `user_id.name` (a person).
- vendor, supplier : `partner_id.commercial_partner_id.name` (a company).
- vendor country : `partner_id.country_id.name`.
- amounts of an order : `amount_untaxed` (without tax, the default), `amount_total` (with tax), `amount_tax`.
- dates : `date_order` (order date, the default), `date_planned` (expected receipt), `effective_date` (received).
- `state` : draft = RFQ, sent = RFQ sent, to approve, purchase = confirmed order, done = locked order, cancel.
  "orders" and "confirmed" mean state in ["purchase", "done"] ; "RFQs" and "quotations" mean state in ["draft", "sent", "to approve"] ; ignore cancel unless asked.
- `receipt_status` : pending, partial, full. `invoice_status` : no, to invoice, invoiced.
- On order lines (`purchase.order.line`) : product `product_id.name`, category `product_id.categ_id.complete_name`, ordered `product_qty`, received `qty_received`, unit price `price_unit`, line total `price_subtotal`.

## Examples
Average order by buyer, confirmed only :
d_next = d.filter(pl.col("state").is_in(["purchase", "done"])).group_by("user_id.name").agg(pl.col("amount_untaxed").mean().round(0).alias("average")).sort("average", descending=True)

Top 5 vendors by spend :
d_next = d.filter(pl.col("state").is_in(["purchase", "done"])).group_by("partner_id.commercial_partner_id.name").agg(pl.col("amount_untaxed").sum().alias("spend")).sort("spend", descending=True).head(5)
