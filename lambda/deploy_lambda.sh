#!/bin/bash

# Enhanced Lambda deployment script with Bedrock configuration support
# This script packages and deploys Lambda functions with all dependencies

set -e  # Exit on error

echo "========================================="
echo "Lambda Deployment Script"
echo "========================================="
echo ""

# Configuration
PRE_LAMBDA_NAME="${PRE_LAMBDA_NAME:-groundtruth-pre-annotation-retirement-coach}"
POST_LAMBDA_NAME="${POST_LAMBDA_NAME:-groundtruth-post-annotation-retirement-coach}"
AWS_REGION="${AWS_REGION:-us-east-1}"
AWS_ACCOUNT_ID="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text)}"

# Bedrock configuration (loaded from config file)
CONFIG_FILE="../config/bedrock_config.json"
if [ -f "$CONFIG_FILE" ]; then
    MODEL_ID=$(jq -r '.model_id' "$CONFIG_FILE")
    MAX_TOKENS=$(jq -r '.inference_params.max_tokens' "$CONFIG_FILE")
    TEMPERATURE=$(jq -r '.inference_params.temperature' "$CONFIG_FILE")
    SYSTEM_PROMPT=$(jq -r '.system_prompt' "$CONFIG_FILE")
else
    MODEL_ID="anthropic.claude-3-sonnet-20240229-v1:0"
    MAX_TOKENS="1000"
    TEMPERATURE="0.7"
    SYSTEM_PROMPT=""
fi

echo "Configuration:"
echo "  Pre-Lambda Name: $PRE_LAMBDA_NAME"
echo "  Post-Lambda Name: $POST_LAMBDA_NAME"
echo "  AWS Region: $AWS_REGION"
echo "  AWS Account: $AWS_ACCOUNT_ID"
echo "  Bedrock Model: $MODEL_ID"
echo ""

# Check if jq is installed (needed for JSON parsing)
if ! command -v jq &> /dev/null; then
    echo "Warning: jq is not installed. Using default configuration values."
fi

# Create deployment packages directory
mkdir -p packages/pre-annotation
mkdir -p packages/post-annotation
mkdir -p dist

echo "Step 1: Packaging pre-annotation Lambda..."
echo "-----------------------------------------"

# Clean previous builds
rm -rf packages/pre-annotation/*
cp pre_annotation_lambda.py packages/pre-annotation/

# Install dependencies
cd packages/pre-annotation/
pip install boto3 -t . -q

# Create zip file
zip -r ../../dist/pre-annotation-lambda.zip . -q
cd ../..

echo "✓ Pre-annotation Lambda packaged: dist/pre-annotation-lambda.zip"
echo ""

echo "Step 2: Packaging post-annotation Lambda..."
echo "-----------------------------------------"

# Clean previous builds
rm -rf packages/post-annotation/*
cp post_annotation_lambda.py packages/post-annotation/

# Install dependencies (including psycopg2 for Aurora)
cd packages/post-annotation/
pip install boto3 psycopg2-binary -t . -q

# Create zip file
zip -r ../../dist/post-annotation-lambda.zip . -q
cd ../..

echo "✓ Post-annotation Lambda packaged: dist/post-annotation-lambda.zip"
echo ""

# Ask if user wants to deploy
read -p "Do you want to deploy these Lambda functions now? (y/n) " -n 1 -r
echo ""

if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Deployment skipped. Zip files are ready in dist/ directory."
    echo "You can deploy manually using AWS Console or CLI."
    exit 0
fi

echo "Step 3: Deploying Lambda functions..."
echo "-----------------------------------------"

# Check if Lambda functions exist
PRE_EXISTS=$(aws lambda get-function --function-name "$PRE_LAMBDA_NAME" 2>/dev/null && echo "yes" || echo "no")
POST_EXISTS=$(aws lambda get-function --function-name "$POST_LAMBDA_NAME" 2>/dev/null && echo "yes" || echo "no")

# Deploy pre-annotation Lambda
if [ "$PRE_EXISTS" = "yes" ]; then
    echo "Updating existing pre-annotation Lambda..."
    aws lambda update-function-code \
        --function-name "$PRE_LAMBDA_NAME" \
        --zip-file fileb://dist/pre-annotation-lambda.zip \
        --region "$AWS_REGION" > /dev/null

    # Update environment variables
    aws lambda update-function-configuration \
        --function-name "$PRE_LAMBDA_NAME" \
        --environment "Variables={
            BEDROCK_MODEL_ID=$MODEL_ID,
            MAX_TOKENS=$MAX_TOKENS,
            TEMPERATURE=$TEMPERATURE,
            ENABLE_CACHING=true,
            CACHE_BUCKET=${CACHE_BUCKET:-},
            MAX_RETRIES=3
        }" \
        --timeout 120 \
        --memory-size 512 \
        --region "$AWS_REGION" > /dev/null

    echo "✓ Pre-annotation Lambda updated"
else
    echo "Error: Lambda function '$PRE_LAMBDA_NAME' not found."
    echo "Please create it first using AWS Console or:"
    echo ""
    echo "  aws lambda create-function \\"
    echo "    --function-name $PRE_LAMBDA_NAME \\"
    echo "    --runtime python3.11 \\"
    echo "    --role arn:aws:iam::$AWS_ACCOUNT_ID:role/GroundTruthPreAnnotationLambdaRole \\"
    echo "    --handler pre_annotation_lambda.lambda_handler \\"
    echo "    --zip-file fileb://dist/pre-annotation-lambda.zip \\"
    echo "    --timeout 120 \\"
    echo "    --memory-size 512 \\"
    echo "    --environment \"Variables={BEDROCK_MODEL_ID=$MODEL_ID,MAX_TOKENS=$MAX_TOKENS,TEMPERATURE=$TEMPERATURE}\""
fi

# Deploy post-annotation Lambda
if [ "$POST_EXISTS" = "yes" ]; then
    echo "Updating existing post-annotation Lambda..."
    aws lambda update-function-code \
        --function-name "$POST_LAMBDA_NAME" \
        --zip-file fileb://dist/post-annotation-lambda.zip \
        --region "$AWS_REGION" > /dev/null

    echo "✓ Post-annotation Lambda updated"
else
    echo "Error: Lambda function '$POST_LAMBDA_NAME' not found."
    echo "Please create it first using the instructions in README.md"
fi

echo ""
echo "========================================="
echo "Deployment Complete!"
echo "========================================="
echo ""
echo "Lambda Functions:"
echo "  Pre-annotation:  $PRE_LAMBDA_NAME"
echo "  Post-annotation: $POST_LAMBDA_NAME"
echo ""
echo "Next steps:"
echo "1. Test the Lambda functions:"
echo "   python ../config/test_bedrock_integration.py --lambda-name $PRE_LAMBDA_NAME"
echo ""
echo "2. Create a Ground Truth labeling job:"
echo "   python ../config/create_groundtruth_job.py ..."
echo ""
