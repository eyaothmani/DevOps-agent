import boto3

from evaluation.mttr.config import AWS_REGION


def create_cloudwatch_client():
    """Create a CloudWatch client configured for the MTTR evaluation."""
    return boto3.client(
        "cloudwatch",
        region_name=AWS_REGION,
    )