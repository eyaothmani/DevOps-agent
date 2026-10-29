from evaluation.api.dependencies import metric_params


def test_metric_params_defaults():
    mode, alarm_type = metric_params(
        mode="auto",
        alarm_type=None,
    )

    assert mode == "auto"
    assert alarm_type is None


def test_metric_params_custom_values():
    mode, alarm_type = metric_params(
        mode="offline",
        alarm_type="cpu-high",
    )

    assert mode == "offline"
    assert alarm_type == "cpu-high"