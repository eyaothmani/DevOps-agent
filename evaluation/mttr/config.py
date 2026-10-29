import os

ALARM_NAME_TEMPLATE = os.getenv(
    "CLOUDWATCH_ALARM_NAME_TEMPLATE",
    "{alarm_type}",
)

SEARCH_WINDOW_MINUTES_BEFORE = int(
    os.getenv("MTTR_WINDOW_BEFORE_MIN", "2"),
)

SEARCH_WINDOW_MINUTES_AFTER = int(
    os.getenv("MTTR_WINDOW_AFTER_MIN", "30"),
)

AWS_REGION = os.getenv(
    "AWS_REGION",
    os.getenv("AWS_DEFAULT_REGION", "eu-north-1"),
)