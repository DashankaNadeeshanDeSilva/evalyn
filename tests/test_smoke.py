import subprocess
import sys

def test_version_importable():
    import evalyn
    assert evalyn.__version__

def test_cli_help_runs():
    out = subprocess.run([sys.executable, "-m", "evalyn.cli", "--help"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert "gate" in out.stdout
