# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.

import datetime
import json
from copy import deepcopy
from typing import Any, Iterator

from botocore.client import BaseClient as BotoBaseClient

from share import shared_logger
from storage import CommonStorage, StorageFactory

from .event import _default_event


def _from_awslogs_data_to_event(awslogs_data: str) -> Any:
    """
    Returns cloudwatch logs event from base64 encoded and gzipped payload
    """
    storage: CommonStorage = StorageFactory.create(storage_type="payload", payload=awslogs_data)
    cloudwatch_logs_payload_plain = storage.get_as_string()
    return json.loads(cloudwatch_logs_payload_plain)


def _handle_cloudwatch_logs_continuation(
    sqs_client: BotoBaseClient,
    sqs_continuing_queue: str,
    last_ending_offset: int,
    cloudwatch_logs_event: dict[str, Any],
    current_log_event: int,
    event_input_id: str,
    config_yaml: str,
) -> None:
    """
    Handler of the continuation queue for cloudwatch logs inputs
    If a cloudwatch logs data payload cannot be fully processed before the
    timeout of the lambda this handler will be called: it will
    send new sqs messages for the unprocessed payload to the
    internal continuing sqs queue
    """

    log_group_name = cloudwatch_logs_event["logGroup"]
    log_stream_name = cloudwatch_logs_event["logStream"]
    logs_events = cloudwatch_logs_event["logEvents"][current_log_event:]

    for log_event in logs_events:
        sqs_client.send_message(
            QueueUrl=sqs_continuing_queue,
            MessageBody=log_event["message"],
            MessageAttributes={
                "config": {"StringValue": config_yaml, "DataType": "String"},
                "originalEventId": {"StringValue": log_event["id"], "DataType": "String"},
                "originalEventSourceARN": {"StringValue": event_input_id, "DataType": "String"},
                "originalLogGroup": {"StringValue": log_group_name, "DataType": "String"},
                "originalLogStream": {"StringValue": log_stream_name, "DataType": "String"},
                "originalLastEndingOffset": {"StringValue": str(last_ending_offset), "DataType": "Number"},
            },
        )

        shared_logger.debug(
            "continuing",
            extra={
                "sqs_continuing_queue": sqs_continuing_queue,
                "body": log_event["message"],
                "last_ending_offset": last_ending_offset,
                "event_id": log_event["id"],
            },
        )


def _handle_cloudwatch_logs_event(event: dict[str, Any], aws_region: str) -> Iterator[tuple[dict[str, Any], int, int]]:
    """
    Handler for cloudwatch logs inputs.
    It iterates through the logEvents in cloudwatch logs trigger payload and process
    content of body payload in the log event.
    If a log event cannot be fully processed before the
    timeout of the lambda it will call the sqs continuing handler
    """

    log_group_name = event["logGroup"]
    log_stream_name = event["logStream"]

    if "logEvents" in event:
        for cloudwatch_log_event_n, cloudwatch_log_event in enumerate(event["logEvents"]):
            event_id = cloudwatch_log_event["id"]

            storage_message: CommonStorage = StorageFactory.create(
                storage_type="payload", payload=cloudwatch_log_event["message"]
            )

            events = storage_message.get_by_lines(
                range_start=0,
            )

            for log_event, ending_offset, newline_length in events:
                assert isinstance(log_event, bytes)

                es_event = deepcopy(_default_event)
                es_event["@timestamp"] = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                es_event["fields"]["message"] = log_event.decode("UTF-8")
                es_event["fields"]["log"]["offset"] = ending_offset - (len(log_event) + newline_length)

                es_event["fields"]["log"]["file"]["path"] = f"{log_group_name}/{log_stream_name}"

                es_event["fields"]["aws"] = {
                    "cloudwatch_logs": {
                        "group_name": log_group_name,
                        "stream_name": log_stream_name,
                        "event_id": event_id,
                    }
                }

                es_event["fields"]["cloud"]["region"] = aws_region

                yield es_event, ending_offset, cloudwatch_log_event_n
