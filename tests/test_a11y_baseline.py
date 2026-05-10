"""Lightweight a11y baseline check (full axe-core CI は別 lane)."""
import pathlib, re, pytest
ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SAMPLE = ["index.html", "pricing.html", "playground.html", "dashboard.html",
          "support.html", "tos.html", "privacy.html", "tokushoho.html"]
@pytest.mark.parametrize("fname", SAMPLE)
def test_viewport_meta(fname):
    f = SITE / fname
    if not f.exists(): pytest.skip(f"{fname} not present")
    txt = f.read_text("utf-8", errors="ignore")
    assert 'name="viewport"' in txt, f"{fname}: viewport meta missing"
@pytest.mark.parametrize("fname", SAMPLE)
def test_lang_attr(fname):
    f = SITE / fname
    if not f.exists(): pytest.skip(f"{fname} not present")
    txt = f.read_text("utf-8", errors="ignore")
    assert re.search(r'<html[^>]*lang=', txt), f"{fname}: <html lang> missing"
@pytest.mark.parametrize("fname", SAMPLE)
def test_main_landmark(fname):
    f = SITE / fname
    if not f.exists(): pytest.skip(f"{fname} not present")
    txt = f.read_text("utf-8", errors="ignore")
    assert re.search(r'<main\b|role="main"', txt), f"{fname}: <main> landmark missing"
