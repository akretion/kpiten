# the .ods is written 50 000 rows at a time : its limit goes from 50 000 to 500 000 rows,
# where it was left at the old default
def migrate(cr, version):
    cr.execute("UPDATE kt_config SET ods_max_rows = 500000 WHERE ods_max_rows = 50000")
