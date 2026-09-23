import subprocess
import sys


def test_the_core_computes_without_drawing_libraries():
    """The core computes data : plotly and great_tables are only for the `render`
    extra (`kpiten_core.render`), a front may do without them."""
    code = (
        "import sys, kpiten_core.tiles, kpiten_core.ods, kpiten_core.plugins, "
        "kpiten_core.numfmt ; "
        "print(sorted(m for m in ('plotly', 'great_tables') if m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"
