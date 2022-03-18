### v0.25.0 - 2022/03/15
##### Features
* Support handling of continuing queue with batch size greater than 1: [#95](https://github.com/elastic/elastic-serverless-forwarder/pull/95)

### v0.24.0 - 2022/03/15
##### Features
* Add support for CloudWatch Logs subscription filter input: [#94](https://github.com/elastic/elastic-serverless-forwarder/pull/94)

### v0.23.0 - 2022/03/09
##### Features
* Add support for direct `sqs` input: [#91](https://github.com/elastic/elastic-serverless-forwarder/pull/91)

### v0.22.0 - 2022/03/03
##### Features
* Set default `S3_CONFIG_FILE` env variable to "s3://": [#90](https://github.com/elastic/elastic-serverless-forwarder/pull/90)

### v0.21.1 - 2022/02/17
##### Bug fixes
* Remove `aws.lambda`, `aws.sns` and `aws.s3_storage_lens` metrics datasets auto-discovery [#82](https://github.com/elastic/elastic-serverless-forwarder/pull/82)


### v0.21.0 - 2022/02/15
##### Breaking changes
* Add support for sending data to an index or alias on top of datastream for the Elasticsearch output (`dataset` and `namespace` config params replaced by `es_index_or_datastream_name`): [#73](https://github.com/elastic/elastic-serverless-forwarder/pull/73)

### v0.20.1 - 2022/02/08
##### Bug fixes
* Set HTTP compression always on and max retries to not exceed 15 mins in the ES client [#69](https://github.com/elastic/elastic-serverless-forwarder/pull/69)

### v0.20.0 - 2022/02/07
##### Features
* Add support for `kinesis-data-stream` input: [#66](https://github.com/elastic/elastic-serverless-forwarder/pull/66)

### v0.19.0 - 2022/02/02
##### Features
* Expose `batch_max_actions` and `batch_max_bytes` config params for ES shipper: [#65](https://github.com/elastic/elastic-serverless-forwarder/pull/65)

### v0.18.0 - 2022/01/13
##### Features
* Handle batches of SQS records: [#63](https://github.com/elastic/elastic-serverless-forwarder/pull/63)

### v0.17.0 - 2021/12/30
##### Features
* Replay queue for ES ingestion phase failure: [#60](https://github.com/elastic/elastic-serverless-forwarder/pull/60)

### v0.16.0 - 2021/12/17
##### Features
* Routing support for AWS Services logs: [#58](https://github.com/elastic/elastic-serverless-forwarder/pull/58)

### v0.15.0 - 2021/12/24
##### Features
* Let the Lambda fail and end up in built-in retry mechanism in case of errors before ingestion phase: [#57](https://github.com/elastic/elastic-serverless-forwarder/pull/57)

### v0.14.0 - 2021/12/17
##### Features
* Support for tags: [#45](https://github.com/elastic/elastic-serverless-forwarder/pull/45)

### v0.13.0 - 2021/12/14
##### Features
* General performance refactoring after stress test outcome: [#48](https://github.com/elastic/elastic-serverless-forwarder/pull/48)

### v0.12.0 - 2021/12/06
##### Features
* Support for Secrets Manager: [#42](https://github.com/elastic/elastic-serverless-forwarder/pull/42)

### v0.11.0 - 2021/11/04
##### Bug fixes
* Integration tests for AWS Lambda handler: [#24](https://github.com/elastic/elastic-serverless-forwarder/pull/24)
* Proper handling of empty lines in `by_lines` decorator: [#26](https://github.com/elastic/elastic-serverless-forwarder/pull/26)

### v0.10.0 - 2021/11/03
##### Features
* Support for cloud_id and api_key in elasticsearch client: [#14](https://github.com/elastic/elastic-serverless-forwarder/pull/14)
##### Bug fixes
* Tests for remaining packages: [#12](https://github.com/elastic/elastic-serverless-forwarder/pull/12)

### v0.9.0 - 2021/10/20
##### Features
* Optimise storage memory usage: [#11](https://github.com/elastic/elastic-serverless-forwarder/pull/11)
##### Bug fixes
* Tests for share packages: [#10](https://github.com/elastic/elastic-serverless-forwarder/pull/10)

### v0.8.0 - 2021/10/19
##### Bug fixes
* Refactoring in offset marker: [#9](https://github.com/elastic/elastic-serverless-forwarder/pull/9)

### v0.5.4 - 2021/10/12
##### Features
* Support for type checking and related refactoring: [#8](https://github.com/elastic/elastic-serverless-forwarder/pull/8)


### v0.3.14 - 2021/10/07
##### Features
* Config support on AWS Lambda handler: [#7](https://github.com/elastic/elastic-serverless-forwarder/pull/7)

### v0.0.15 - 2021/09/10
##### Features
* First draft of the AWS Lambda handler with no config: [#2](https://github.com/elastic/elastic-serverless-forwarder/pull/2)

### v0.0.1-dev0 - 2021/09/07

#### Bootstrapping the project for Elastic Serverless Forwarder
