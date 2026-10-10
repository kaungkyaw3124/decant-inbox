import pytest

from app.parser.normalize import normalize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("5ml stronger with you intensely ရှိလား", "5ml stronger with you intensely ရှိလား"),
        ("stw intensely ၅ ml ဝယ်ချင်လို့ပါ", "stw intensely 5 ml ဝယ်ချင်လို့ပါ"),
        ("STW  Intensely 10mL", "stw intensely 10ml"),
        ("10 ml.", "10 ml"),
        ("၁၀ မီလီလီတာ", "10 ml"),
        ("၃ မီလီ", "3 ml"),
        ("  Sauvage\tEDP  ", "sauvage edp"),
        # Zawgyi input is converted to Unicode.
        ("stw intensely ၅ ml ဝယ္ခ်င္လို႔ပါ", "stw intensely 5 ml ဝယ်ချင်လို့ပါ"),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected
