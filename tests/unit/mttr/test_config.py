from evaluation.mttr import config


def test_default_alarm_name_template():
    assert config.ALARM_NAME_TEMPLATE == "{alarm_type}"


def test_default_search_window_before():
    assert config.SEARCH_WINDOW_MINUTES_BEFORE == 2


def test_default_search_window_after():
    assert config.SEARCH_WINDOW_MINUTES_AFTER == 30


def test_default_aws_region():
    assert config.AWS_REGION == "eu-north-1"