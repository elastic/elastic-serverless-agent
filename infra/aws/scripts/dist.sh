#!/usr/bin/env bash

set -e

if [[ $# -ne 3 ]]
then
    echo "Usage: $0 bucket-name account-id region"
    exit 1
fi

BUCKET="$1"
ACCOUNT_ID="$2"
REGION="$3"

TMPDIR=$(mktemp -d /tmp/dist.XXXXXXXXXX)

mkdir "${TMPDIR}/packages"
pip3 install --upgrade --target "${TMPDIR}/packages" -r tests/requirements/requirements.txt

pushd "${TMPDIR}/packages"
zip -r "${TMPDIR}/lambda.zip" .

popd
zip -r -g "${TMPDIR}/lambda.zip" share
zip -r -g "${TMPDIR}/lambda.zip" shippers
zip -r -g "${TMPDIR}/lambda.zip" storage

pushd handlers/aws
zip -g "${TMPDIR}/lambda.zip" *.py

aws s3api get-bucket-location --bucket "${BUCKET}" || aws s3api create-bucket --acl private --bucket "${BUCKET}" --region "${REGION}" --create-bucket-configuration LocationConstraint="${REGION}"
aws s3 cp "${TMPDIR}/lambda.zip" "s3://${BUCKET}/lambda.zip"

popd
cat <<EOF > "${TMPDIR}/policy.json"
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service":  "serverlessrepo.amazonaws.com"
            },
            "Action": "s3:GetObject",
            "Resource": "arn:aws:s3:::${BUCKET}/*",
            "Condition" : {
                "StringEquals": {
                    "aws:SourceAccount": "${ACCOUNT_ID}"
                }
            }
        }
    ]
}
EOF

aws s3api put-bucket-policy --bucket "${BUCKET}" --policy "file://${TMPDIR}/policy.json"

sed -e "s/%codeUriBucket%/${BUCKET}/g" infra/aws/cloudformation/template.yaml > "${TMPDIR}/template.yaml"

sam package --template-file "${TMPDIR}/template.yaml" --output-template-file "${TMPDIR}/packaged.yaml" --s3-bucket "${BUCKET}"
sam publish --template "${TMPDIR}/packaged.yaml" --region "${REGION}"

rm -rf "${TMPDIR}"
