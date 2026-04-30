def test_core_utils_math():
    assert sum([1, 2, 3]) == 6


from api.core.stock_utils import normalize_symbol


def test_normalize_symbol_supports_beijing_exchange_suffix():
    assert normalize_symbol("899050.BJ") == "899050.BJ"


def test_normalize_symbol_infers_beijing_exchange_for_8_prefix():
    assert normalize_symbol("830000") == "830000.BJ"
