# a panel without a sequence came after "Main" (Postgres puts an empty sequence last)
def migrate(cr, version):
    cr.execute("UPDATE kt_panel SET sequence = 10 WHERE sequence IS NULL")
