#!/bin/bash

# Script to package Lambda functions with dependencies for deployment

echo "Packaging Lambda functions..."

# Create directories for packaging
mkdir -p packages/pre-annotation
mkdir -p packages/post-annotation

# Package pre-annotation Lambda
echo "Packaging pre-annotation Lambda..."
cp pre_annotation_lambda.py packages/pre-annotation/
cd packages/pre-annotation/
pip install boto3 -t .
zip -r ../../pre-annotation-lambda.zip .
cd ../..

# Package post-annotation Lambda with psycopg2
echo "Packaging post-annotation Lambda..."
cp post_annotation_lambda.py packages/post-annotation/
cd packages/post-annotation/
pip install -r ../../requirements.txt -t .
zip -r ../../post-annotation-lambda.zip .
cd ../..

echo "Lambda packages created:"
echo "  - pre-annotation-lambda.zip"
echo "  - post-annotation-lambda.zip"
echo ""
echo "Upload these zip files when creating Lambda functions in AWS Console or use AWS CLI:"
echo "  aws lambda create-function --function-name groundtruth-pre-annotation ..."
echo "  aws lambda create-function --function-name groundtruth-post-annotation ..."
