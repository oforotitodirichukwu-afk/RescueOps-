"""Creates the AWS resources for docker-compose. On Kubernetes, Terraform owns these instead."""

import json

import boto3
from botocore.exceptions import ClientError

PREFIX = "rescueops"
session = boto3.session.Session()

dynamodb = session.client("dynamodb")
for table, key in ((f"{PREFIX}-incidents", "incident_id"), (f"{PREFIX}-ambulances", "ambulance_id")):
    try:
        dynamodb.create_table(
            TableName=table,
            KeySchema=[{"AttributeName": key, "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        print(f"created table {table}")
    except ClientError as err:
        if err.response["Error"]["Code"] != "ResourceInUseException":
            raise
        print(f"table {table} exists")

sqs = session.client("sqs")
dlq_url = sqs.create_queue(QueueName=f"{PREFIX}-dispatch-dlq")["QueueUrl"]
dlq_arn = sqs.get_queue_attributes(QueueUrl=dlq_url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
sqs.create_queue(
    QueueName=f"{PREFIX}-dispatch-requests",
    Attributes={
        "VisibilityTimeout": "30",
        "RedrivePolicy": json.dumps({"deadLetterTargetArn": dlq_arn, "maxReceiveCount": "10"}),
    },
)
print("queues ready")

s3 = session.client("s3")
try:
    s3.create_bucket(Bucket=f"{PREFIX}-dispatch-reports")
except ClientError as err:
    if err.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
        raise
print("bucket ready")
