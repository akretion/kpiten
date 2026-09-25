# a graph at the old default height (260 px) gets the new one (320 px) : its category
# labels took most of it ; a tile resized by a user keeps its height
def migrate(cr, version):
    cr.execute(
        "UPDATE kt_kpi SET tile_height = 320"
        " WHERE kind = 'graph' AND (tile_height = 260 OR tile_height IS NULL)"
    )
