from app.utils.priority import parse_priority_map


def test_parse_priority_map_from_json():
    default = {"sync": 1}
    env_value = '{"sync": 5, "retry": 3}'
    mapping = parse_priority_map(env_value, default)
    assert mapping == {"sync": 5, "retry": 3}


def test_parse_priority_map_from_csv_fallback():
    default = {"sync": 1}
    mapping = parse_priority_map("matching:2, retry:4", default)
    assert mapping == {"matching": 2, "retry": 4}


def test_parse_priority_map_invalid_returns_default_copy():
    default = {"sync": 1}
    mapping = parse_priority_map("not-valid", default)
    assert mapping == default
    assert mapping is not default
