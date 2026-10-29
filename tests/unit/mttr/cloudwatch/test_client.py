from unittest.mock import MagicMock, patch

from evaluation.mttr.cloudwatch.client import create_cloudwatch_client


@patch("evaluation.mttr.cloudwatch.client.boto3.client")
def test_create_cloudwatch_client(mock_boto_client):
    expected_client = MagicMock()
    mock_boto_client.return_value = expected_client

    result = create_cloudwatch_client()

    assert result is expected_client

    mock_boto_client.assert_called_once_with(
        "cloudwatch",
        region_name="eu-north-1",
    )