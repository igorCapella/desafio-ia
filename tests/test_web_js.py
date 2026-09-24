import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js não instalado")
def test_nucleo_js():
    r = subprocess.run(["node", "--test", "tests/web/nucleo.test.cjs"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
