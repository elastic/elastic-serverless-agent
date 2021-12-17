# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.

import base64
import gzip
import json
import os
import time
from copy import deepcopy
from typing import Any, Optional, Union
from unittest import TestCase

import docker
import mock
import pytest
from botocore.exceptions import ClientError
from elasticsearch import Elasticsearch
from localstack.services.s3.s3_starter import check_s3
from localstack.services.secretsmanager.secretsmanager_starter import check_secretsmanager
from localstack.services.sqs.sqs_starter import check_sqs
from localstack.utils import testutil
from localstack.utils.aws import aws_stack

from main_aws import handler


class ContextMock:
    aws_request_id = "aws_request_id"
    invoked_function_arn = "invoked:function:arn:invoked:function:arn"

    @staticmethod
    def get_remaining_time_in_millis() -> int:
        return 0


class MockContent:
    SECRETS_MANAGER_MOCK_DATA: dict[str, dict[str, str]] = {
        "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets": {
            "type": "SecretString",
            "data": json.dumps(
                {
                    "url": "mock_elastic_url",
                    "username": "mock_elastic_username",
                    "password": "mock_elastic_password",
                }
            ),
        },
        "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secret": {
            "type": "SecretString",
            "data": "mock_plain_text_sqs_arn",
        },
        "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:binary_secret": {
            "type": "SecretBinary",
            "data": "bW9ja19uZ2lueC5sb2c=",
        },
        "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:empty_secret": {"type": "SecretString", "data": ""},
    }

    @staticmethod
    def _get_aws_sm_client(region_name: str) -> mock.MagicMock:
        client = mock.Mock()
        client.get_secret_value = MockContent.get_secret_value
        return client

    @staticmethod
    def get_secret_value(SecretId: str) -> Optional[dict[str, Union[bytes, str]]]:
        secrets = MockContent.SECRETS_MANAGER_MOCK_DATA.get(SecretId)

        if secrets is None:
            raise ClientError(
                {
                    "Error": {
                        "Message": "Secrets Manager can't find the specified secret.",
                        "Code": "ResourceNotFoundException",
                    }
                },
                "GetSecretValue",
            )

        if secrets["type"] == "SecretBinary":
            return {"SecretBinary": base64.b64decode(secrets["data"])}
        elif secrets["type"] == "SecretString":
            return {"SecretString": secrets["data"]}

        return None


@pytest.mark.unit
class TestLambdaHandlerFailure(TestCase):
    def test_lambda_handler_failure(self) -> None:
        dummy_event: dict[str, Any] = {
            "Records": [
                {
                    "eventSource": "aws:sqs",
                },
            ]
        }

        event_with_config: dict[str, Any] = {
            "Records": [
                {
                    "messageAttributes": {
                        "config": {"stringValue": "ADD_CONFIG_STRING_HERE", "dataType": "String"},
                        "originalEventSource": {
                            "stringValue": "dummy_aws_sqs",
                            "dataType": "String",
                        },
                    },
                    "md5OfBody": "randomhash",
                    "eventSource": "aws:sqs",
                    "eventSourceARN": "arn:aws:sqs",
                    "awsRegion": "eu-central-1",
                }
            ]
        }

        with self.subTest("Invalid s3 uri"):
            os.environ["S3_CONFIG_FILE"] = ""
            ctx = ContextMock()

            call = handler(dummy_event, ctx)  # type:ignore

            assert call == "exception raised: ValueError('Invalid s3 uri provided: ``')"

        with self.subTest("Invalid s3 uri no bucket and key"):
            os.environ["S3_CONFIG_FILE"] = "s3://"
            ctx = ContextMock()

            call = handler(dummy_event, ctx)  # type:ignore

            assert call == "exception raised: ValueError('Invalid s3 uri provided: `s3://`')"

        with self.subTest("no Records in event"):
            ctx = ContextMock()
            event: dict[str, Any] = {}

            call = handler(event, ctx)  # type:ignore

            assert call == "exception raised: Exception('Not supported trigger')"

        with self.subTest("empty Records in event"):
            ctx = ContextMock()
            event = {"Records": []}

            call = handler(event, ctx)  # type:ignore

            assert call == "exception raised: Exception('Not supported trigger')"

        with self.subTest("no eventSource in Records in event"):
            ctx = ContextMock()
            event = {"Records": [{}]}

            call = handler(event, ctx)  # type:ignore

            assert call == "exception raised: Exception('Not supported trigger')"

        with self.subTest("no valid eventSource in Records in event"):
            ctx = ContextMock()
            event = {"Records": [{"eventSource": "invalid"}]}

            call = handler(event, ctx)  # type:ignore

            assert call == "exception raised: Exception('Not supported trigger')"

        with self.subTest("invalid secretsmanager: arn format too long"):
            ctx = ContextMock()
            config_yml: str = """
                inputs:
                  - type: "sqs"
                    id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secret:THIS:IS:INVALID"
                    outputs:
                      - type: "elasticsearch"
                        args:
                          elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:url"
                          username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                          password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                          dataset: "redis.log"
                          namespace: "default"
            """
            event = deepcopy(event_with_config)
            event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

            call = handler(event, ctx)  # type:ignore

            assert (
                call == "exception raised: SyntaxError('Invalid arn format: "
                "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secret:THIS:IS:INVALID')"
            )

        with self.subTest("invalid secretsmanager: empty region"):
            ctx = ContextMock()
            # BEWARE region is empty at id
            config_yml = """
                inputs:
                  - type: "sqs"
                    id: "arn:aws:secretsmanager::123-456-789:secret:plain_secret"
                    outputs:
                      - type: "elasticsearch"
                        args:
                          elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets"
                          username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                          password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                          dataset: "redis.log"
                          namespace: "default"
            """

            event = deepcopy(event_with_config)
            event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

            call = handler(event, ctx)  # type:ignore

            assert (
                call == "exception raised: ValueError('Must be provided region in arn: "
                "arn:aws:secretsmanager::123-456-789:secret:plain_secret')"
            )

        with self.subTest("invalid secretsmanager: empty secrets manager name"):
            ctx = ContextMock()
            # BEWARE empty secrets manager name at id
            config_yml = """
                inputs:
                  - type: "sqs"
                    id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:"
                    outputs:
                      - type: "elasticsearch"
                        args:
                          elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets"
                          username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                          password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                          dataset: "redis.log"
                          namespace: "default"
            """

            event = deepcopy(event_with_config)
            event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

            call = handler(event, ctx)  # type:ignore

            assert (
                call == "exception raised: ValueError('Must be provided secrets manager name in arn: "
                "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:')"
            )

        with self.subTest("invalid secretsmanager: cannot use both plain text and key/value pairs"):
            ctx = ContextMock()
            # BEWARE using es_secrets plain text for elasticsearch_url and es_secrets:username for username
            config_yml = """
                inputs:
                  - type: "sqs"
                    id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secrets"
                    outputs:
                      - type: "elasticsearch"
                        args:
                          elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets"
                          username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                          password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                          dataset: "redis.log"
                          namespace: "default"
            """

            event = deepcopy(event_with_config)
            event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

            call = handler(event, ctx)  # type:ignore

            assert (
                call == "exception raised: ValueError('You cannot have both plain text and json key for the same "
                "secret: arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username')"
            )

        with mock.patch("share.secretsmanager._get_aws_sm_client", new=MockContent._get_aws_sm_client):
            with self.subTest("invalid secretsmanager: empty secret key"):
                ctx = ContextMock()
                # BEWARE empty key at elasticsearch_url
                config_yml = """
                    inputs:
                      - type: "sqs"
                        id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secret"
                        outputs:
                          - type: "elasticsearch"
                            args:
                              elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:"
                              username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                              password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                              dataset: "redis.log"
                              namespace: "default"
                """

                event = deepcopy(event_with_config)
                event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

                call = handler(event, ctx)  # type:ignore

                assert (
                    call == "exception raised: ValueError('Error for secret "
                    "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:: key must "
                    "not be empty')"
                )

        with mock.patch("share.secretsmanager._get_aws_sm_client", new=MockContent._get_aws_sm_client):
            with self.subTest("invalid secretsmanager: secret does not exist"):
                ctx = ContextMock()
                config_yml = """
                    inputs:
                      - type: "sqs"
                        id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:DOES_NOT_EXIST"
                        outputs:
                          - type: "elasticsearch"
                            args:
                              elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:url"
                              username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                              password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                              dataset: "redis.log"
                              namespace: "default"
                """

                event = deepcopy(event_with_config)
                event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

                call = handler(event, ctx)  # type:ignore

                assert (
                    call
                    == 'exception raised: ClientError("An error occurred (ResourceNotFoundException) when calling '
                    + "the GetSecretValue operation: Secrets Manager can't find the specified secret.\")"
                )

        with mock.patch("share.secretsmanager._get_aws_sm_client", new=MockContent._get_aws_sm_client):
            with self.subTest("invalid secretsmanager: empty secret value"):
                ctx = ContextMock()
                config_yml = """
                    inputs:
                      - type: "sqs"
                        id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:empty_secret"
                        outputs:
                          - type: "elasticsearch"
                            args:
                              elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:url"
                              username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                              password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                              dataset: "redis.log"
                              namespace: "default"
                """

                event = deepcopy(event_with_config)
                event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

                call = handler(event, ctx)  # type:ignore

                assert (
                    call == "exception raised: ValueError('Error for secret "
                    "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:empty_secret: must "
                    "not be empty')"
                )
        with mock.patch("share.secretsmanager._get_aws_sm_client", new=MockContent._get_aws_sm_client):
            with self.subTest("tags not list"):
                ctx = ContextMock()
                config_yml = """
                    inputs:
                      - type: "sqs"
                        id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secret"
                        tags: "tag1"
                        outputs:
                          - type: "elasticsearch"
                            args:
                              elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:url"
                              username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                              password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                              dataset: "redis.log"
                              namespace: "default"
                """

                event = deepcopy(event_with_config)
                event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

                call = handler(event, ctx)  # type:ignore

                assert call == "exception raised: ValueError('Tags must be of type list')"

        with mock.patch("share.secretsmanager._get_aws_sm_client", new=MockContent._get_aws_sm_client):
            with self.subTest("each tag must be of type str"):
                ctx = ContextMock()
                config_yml = """
                    inputs:
                      - type: "sqs"
                        id: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:plain_secret"
                        tags:
                          - "tag1"
                          - 2
                          - "tag3"
                        outputs:
                          - type: "elasticsearch"
                            args:
                              elasticsearch_url: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:url"
                              username: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:username"
                              password: "arn:aws:secretsmanager:eu-central-1:123-456-789:secret:es_secrets:password"
                              dataset: "redis.log"
                              namespace: "default"
                """

                event = deepcopy(event_with_config)
                event["Records"][0]["messageAttributes"]["config"]["stringValue"] = config_yml

                call = handler(event, ctx)  # type:ignore

                assert call, (
                    "exception raised: exception raised: "
                    "ValueError(\"Each tag must be of type str, given: ['tag1', 2, 'tag3']\")"
                )


@pytest.mark.integration
class TestLambdaHandlerSuccess(TestCase):
    def _event_from_sqs_message(self) -> dict[str, Any]:
        sqs_client = aws_stack.connect_to_service("sqs")
        messages = sqs_client.receive_message(
            QueueUrl=self._continuing_queue_info["QueueUrl"], MaxNumberOfMessages=2, MessageAttributeNames=["All"]
        )

        assert "Messages" in messages
        assert len(messages["Messages"]) == 1

        message = messages["Messages"][0]
        message["body"] = message["Body"]
        message["messageAttributes"] = message["MessageAttributes"]
        for attribute in message["messageAttributes"]:
            new_attribute = deepcopy(message["messageAttributes"][attribute])
            for attribute_key in message["messageAttributes"][attribute]:
                camel_case_key = "".join([attribute_key[0].lower(), attribute_key[1:]])
                new_attribute[camel_case_key] = new_attribute[attribute_key]
                message["messageAttributes"][attribute] = new_attribute

        message["eventSource"] = "aws:sqs"
        message["eventSourceARN"] = self._continuing_queue_info["QueueArn"]
        return dict(Records=[message])

    def _create_secrets(self, secret_name: str, secret_data: dict[str, str]) -> Any:
        client = aws_stack.connect_to_service(
            "secretsmanager", region_name="eu-central-1", endpoint_url=f"http://localhost:{self._LOCALSTACK_HOST_PORT}"
        )
        client.create_secret(Name=secret_name, SecretString=json.dumps(secret_data))

        return client.describe_secret(SecretId=secret_name)["ARN"]

    @staticmethod
    def _upload_content_to_bucket(
        content: Union[bytes, str], content_type: str, bucket_name: str, key_name: str
    ) -> None:
        client = aws_stack.connect_to_service("s3")

        client.create_bucket(Bucket=bucket_name, ACL="public-read-write")
        client.put_object(Bucket=bucket_name, Key=key_name, Body=content, ContentType=content_type)

    def setUp(self) -> None:
        docker_client = docker.from_env()

        self._localstack_container = docker_client.containers.run(
            "localstack/localstack",
            detach=True,
            environment=["SERVICES=s3,sqs,secretsmanager"],
            ports={"4566/tcp": None},
        )

        while (
            "4566/tcp" not in self._localstack_container.ports
            or len(self._localstack_container.ports["4566/tcp"]) == 0
            or "HostPort" not in self._localstack_container.ports["4566/tcp"][0]
        ):
            self._localstack_container.reload()
            time.sleep(1)

        self._TEST_S3_URL = os.environ["TEST_S3_URL"]
        self._TEST_SQS_URL = os.environ["TEST_SQS_URL"]

        self._LOCALSTACK_HOST_PORT: str = self._localstack_container.ports["4566/tcp"][0]["HostPort"]

        os.environ["TEST_S3_URL"] = f"http://localhost:{self._LOCALSTACK_HOST_PORT}"
        os.environ["TEST_SQS_URL"] = f"http://localhost:{self._LOCALSTACK_HOST_PORT}"

        with mock.patch("localstack.services.s3.s3_starter.s3_listener.PORT_S3_BACKEND", self._LOCALSTACK_HOST_PORT):
            while True:
                ready = True
                try:
                    check_s3()
                    time.sleep(1)
                except AssertionError:
                    ready = False

                if ready:
                    break

        with mock.patch("localstack.services.sqs.sqs_starter.PORT_SQS_BACKEND", self._LOCALSTACK_HOST_PORT):
            while True:
                ready = True
                try:
                    check_sqs()
                    time.sleep(1)
                except AssertionError:
                    ready = False

                if ready:
                    break

        with mock.patch(
            "localstack.services.secretsmanager.secretsmanager_starter.PORT_SECRETS_MANAGER_BACKEND",
            self._LOCALSTACK_HOST_PORT,
        ):
            while True:
                ready = True
                try:
                    check_secretsmanager()
                    time.sleep(1)
                except AssertionError:
                    ready = False

                if ready:
                    break

        self._ELASTIC_USER: str = "elastic"
        self._ELASTIC_PASSWORD: str = "password"

        self._secret_arn = self._create_secrets(
            "es_secrets", {"username": self._ELASTIC_USER, "password": self._ELASTIC_PASSWORD}
        )

        self._elastic_container = docker_client.containers.run(
            "docker.elastic.co/elasticsearch/elasticsearch:7.15.1",
            detach=True,
            environment=[
                "ES_JAVA_OPTS=-Xms1g -Xmx1g",
                f"ELASTIC_PASSWORD={self._ELASTIC_PASSWORD}",
                "xpack.security.enabled=true",
                "discovery.type=single-node",
                "network.bind_host=0.0.0.0",
            ],
            ports={"9200/tcp": None},
        )

        while (
            "9200/tcp" not in self._elastic_container.ports
            or len(self._elastic_container.ports["9200/tcp"]) == 0
            or "HostPort" not in self._elastic_container.ports["9200/tcp"][0]
        ):
            self._elastic_container.reload()
            time.sleep(1)

        self._ES_HOST_PORT: str = self._elastic_container.ports["9200/tcp"][0]["HostPort"]

        self._es_client = Elasticsearch(
            hosts=[f"127.0.0.1:{self._ES_HOST_PORT}"],
            scheme="http",
            http_auth=(self._ELASTIC_USER, self._ELASTIC_PASSWORD),
        )

        while not self._es_client.ping():
            time.sleep(1)

        self._es_client.cluster.health(wait_for_status="green")

        self._source_queue_info = testutil.create_sqs_queue("source-queue")
        self._continuing_queue_info = testutil.create_sqs_queue("continuing-queue")

        self._config_yaml: str = f"""
        inputs:
          - type: "sqs"
            id: "{self._source_queue_info["QueueArn"]}"
            tags:
              - "tag1"
              - "tag2"
              - "tag3"
            outputs:
              - type: "elasticsearch"
                args:
                  elasticsearch_url: "http://127.0.0.1:{self._ES_HOST_PORT}"
                  username: "{self._secret_arn}:username"
                  password: "{self._secret_arn}:password"
                  dataset: "redis.log"
                  namespace: "default"
                """

        self._upload_content_to_bucket(
            content=self._config_yaml,
            content_type="text/plain",
            bucket_name="config-bucket",
            key_name="folder/config.yaml",
        )

        redis_log: bytes = (
            "79191:C 08 Jul 2021 13:25:02.609 # oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo\n"
            + "79191:C 08 Jul 2021 13:25:02.610 # Redis version=6.2.4, bits=64, commit=00000000, "
            + "modified=0, pid=79191, just started"
        ).encode("UTF-8")

        self._upload_content_to_bucket(
            content=gzip.compress(redis_log),
            content_type="application/x-gzip",
            bucket_name="test-bucket",
            key_name="folder/redis.log.gz",
        )

        os.environ["S3_CONFIG_FILE"] = "s3://config-bucket/folder/config.yaml"
        os.environ["SQS_CONTINUE_URL"] = self._continuing_queue_info["QueueUrl"]

    def tearDown(self) -> None:
        os.environ["TEST_S3_URL"] = self._TEST_S3_URL
        os.environ["TEST_SQS_URL"] = self._TEST_SQS_URL

        del os.environ["S3_CONFIG_FILE"]
        del os.environ["SQS_CONTINUE_URL"]

        self._elastic_container.stop()
        self._elastic_container.remove()

        self._localstack_container.stop()
        self._localstack_container.remove()

    def test_lambda_handler(self) -> None:
        filename: str = "folder/redis.log.gz"
        with mock.patch("storage.S3Storage._s3_client", aws_stack.connect_to_service("s3")):
            with mock.patch("handlers.aws.sqs_trigger._get_sqs_client", lambda: aws_stack.connect_to_service("sqs")):
                with mock.patch(
                    "share.secretsmanager._get_aws_sm_client",
                    lambda region_name: aws_stack.connect_to_service(
                        "secretsmanager",
                        endpoint_url=f"http://localhost:{self._LOCALSTACK_HOST_PORT}",
                        region_name=region_name,
                    ),
                ):
                    ctx = ContextMock()
                    event = {
                        "Records": [
                            {
                                "messageId": "9b745861-1171-489c-9748-799ed2a3d9da",
                                "body": json.dumps(
                                    {
                                        "Records": [
                                            {
                                                "eventVersion": "2.1",
                                                "eventSource": "aws:s3",
                                                "awsRegion": "eu-central-1",
                                                "eventTime": "2021-09-08T18:34:25.042Z",
                                                "eventName": "ObjectCreated:Put",
                                                "s3": {
                                                    "s3SchemaVersion": "1.0",
                                                    "configurationId": "test-bucket",
                                                    "bucket": {
                                                        "name": "test-bucket",
                                                        "arn": "arn:aws:s3:::test-bucket",
                                                    },
                                                    "object": {
                                                        "key": f"{filename}",
                                                    },
                                                },
                                            }
                                        ]
                                    }
                                ),
                                "eventSource": "aws:sqs",
                                "eventSourceARN": self._source_queue_info["QueueArn"],
                            },
                        ]
                    }

                    first_call = handler(event, ctx)  # type:ignore

                    assert first_call == "continuing"

                    self._es_client.indices.refresh(index="logs-redis.log-default")
                    assert self._es_client.count(index="logs-redis.log-default")["count"] == 1

                    res = self._es_client.search(index="logs-redis.log-default")
                    assert res["hits"]["total"] == {"value": 1, "relation": "eq"}
                    assert (
                        res["hits"]["hits"][0]["_source"]["fields"]["message"]
                        == "79191:C 08 Jul 2021 13:25:02.609 # oO0OoO0OoO0Oo Redis is starting oO0OoO0OoO0Oo"
                    )
                    assert res["hits"]["hits"][0]["_source"]["fields"]["log"] == {
                        "offset": 0,
                        "file": {"path": f"https://test-bucket.s3.eu-central-1.amazonaws.com/{filename}"},
                    }
                    assert res["hits"]["hits"][0]["_source"]["fields"]["aws"] == {
                        "s3": {
                            "bucket": {"name": "test-bucket", "arn": "arn:aws:s3:::test-bucket"},
                            "object": {"key": f"{filename}"},
                        }
                    }
                    assert res["hits"]["hits"][0]["_source"]["fields"]["cloud"] == {
                        "provider": "aws",
                        "region": "eu-central-1",
                    }

                    assert res["hits"]["hits"][0]["_source"]["tags"] == [
                        "preserve_original_event",
                        "forwarded",
                        "redis-log",
                        "tag1",
                        "tag2",
                        "tag3",
                    ]

                    event = self._event_from_sqs_message()
                    second_call = handler(event, ctx)  # type:ignore

                    assert second_call == "continuing"

                    self._es_client.indices.refresh(index="logs-redis.log-default")
                    assert self._es_client.count(index="logs-redis.log-default")["count"] == 2

                    res = self._es_client.search(index="logs-redis.log-default")
                    assert res["hits"]["total"] == {"value": 2, "relation": "eq"}
                    assert (
                        res["hits"]["hits"][1]["_source"]["fields"]["message"]
                        == "79191:C 08 Jul 2021 13:25:02.610 # Redis version=6.2.4, bits=64, commit=00000000, "
                        + "modified=0, pid=79191, just started"
                    )

                    assert res["hits"]["hits"][1]["_source"]["fields"]["log"] == {
                        "offset": 81,
                        "file": {"path": f"https://test-bucket.s3.eu-central-1.amazonaws.com/{filename}"},
                    }
                    assert res["hits"]["hits"][1]["_source"]["fields"]["aws"] == {
                        "s3": {
                            "bucket": {"name": "test-bucket", "arn": "arn:aws:s3:::test-bucket"},
                            "object": {"key": f"{filename}"},
                        }
                    }
                    assert res["hits"]["hits"][1]["_source"]["fields"]["cloud"] == {
                        "provider": "aws",
                        "region": "eu-central-1",
                    }

                    event = self._event_from_sqs_message()
                    third_call = handler(event, ctx)  # type:ignore

                    assert third_call == "completed"
