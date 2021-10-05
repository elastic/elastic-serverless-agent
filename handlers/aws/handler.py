# Copyright Elasticsearch B.V. and/or licensed to Elasticsearch B.V. under one
# or more contributor license agreements. Licensed under the Elastic License 2.0;
# you may not use this file except in compliance with the Elastic License 2.0.

import os

import elasticapm  # noqa: F401
from elasticapm.contrib.serverless.aws import capture_serverless  # noqa: F401
from sqs_trigger import _handle_sqs_continuation, _handle_sqs_event
from utils import from_s3_uri_to_bucket_name_and_object_key, get_trigger_type

from share import Config, ElasticSearchOutput, logger, parse_config
from shippers import CommonShipper, CompositeShipper, ShipperFactory
from storage import CommonStorage, StorageFactory

_completion_grace_period: int = 60000


@capture_serverless()
def lambda_handler(lambda_event, lambda_context):
    try:
        trigger_type: str = get_trigger_type(lambda_event)
        logger.info("trigger", extra={"type": trigger_type})
    except Exception as e:
        logger.exception("exception raised", exc_info=e)
        return str(e)

    try:
        if trigger_type == "self_sqs":
            payload = lambda_event["Records"][0]["messageAttributes"]
            config_yaml = payload["config"]["stringValue"]
            config: Config = parse_config(config_yaml)
            lambda_event["Records"][0]["eventSourceARN"] = payload["originalEventSource"]["stringValue"]

        else:
            config_file: str = os.getenv("S3_CONFIG_FILE")
            if config_file is None:
                return "empty S3_CONFIG_FILE env variable"

            bucket_name, object_key = from_s3_uri_to_bucket_name_and_object_key(config_file)
            logger.info("config file", extra={"bucket_name": bucket_name, "object_key": object_key})

            config_storage: CommonStorage = StorageFactory.create(
                storage_type="s3", bucket_name=bucket_name, object_key=object_key
            )

            config_yaml = config_storage.get_as_string()
            logger.debug("config", extra={"yaml": config_yaml})

            config: Config = parse_config(config_yaml)

    except Exception as e:
        logger.exception("exception raised", exc_info=e)
        return str(e)

    if trigger_type == "sqs" or trigger_type == "self_sqs":
        event_input = config.get_input_by_type_and_id("sqs", lambda_event["Records"][0]["eventSourceARN"])
        if not event_input:
            logger.error(f'no input set for {lambda_event["Records"][0]["eventSourceARN"]}')

            return "not input set"

        logger.info("input", extra={"type": event_input.type, "id": event_input.id})

        sent_event: int = 0
        composite_shipper: CompositeShipper = CompositeShipper()

        try:
            for output_type in event_input.get_output_types():
                if output_type == "elasticsearch":
                    logger.info("setting ElasticSearch shipper")
                    output: ElasticSearchOutput = event_input.get_output_by_type("elasticsearch")
                    shipper: CommonShipper = ShipperFactory.create_from_output(
                        output_type="elasticsearch", output=output
                    )
                    composite_shipper.add_shipper(shipper=shipper)

            for es_event, last_ending_offset, current_sqs_record, current_s3_record in _handle_sqs_event(
                config, lambda_event
            ):
                logger.debug("es_event", extra={"es_event": es_event})

                composite_shipper.send(es_event)
                sent_event += 1

                if (
                    lambda_context is not None
                    and lambda_context.get_remaining_time_in_millis() < _completion_grace_period
                ):
                    sqs_continuing_queue = os.environ["SQS_CONTINUE_URL"]

                    logger.info(
                        "lambda is going to shutdown, continuing on dedicated sqs queue",
                        extra={"sqs_queue": sqs_continuing_queue, "sent_event": sent_event},
                    )

                    composite_shipper.flush()

                    _handle_sqs_continuation(
                        sqs_continuing_queue=sqs_continuing_queue,
                        lambda_event=lambda_event,
                        event_input_id=event_input.id,
                        last_ending_offset=last_ending_offset,
                        current_sqs_record=current_sqs_record,
                        current_s3_record=current_s3_record,
                        config_yaml=config_yaml,
                    )

                    return

            composite_shipper.flush()
            logger.info("lambda processed all the events", extra={"sent_event": sent_event})

        except Exception as e:
            logger.exception("exception raised", exc_info=e)
            logger.error("lambda exited with an error", extra={"sent_event": sent_event})
            return str(e)
