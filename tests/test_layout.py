from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_license_names_the_copyright_holder():
    assert "Milenko x Horrible Dev" in (ROOT / "LICENSE").read_text()
