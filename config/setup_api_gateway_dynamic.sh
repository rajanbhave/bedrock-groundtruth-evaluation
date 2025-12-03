#!/bin/bash

###############################################################################
# Setup API Gateway for Dynamic Ground Truth Evaluation
#
# This script creates:
# 1. Lambda function for Bedrock API
# 2. API Gateway REST API
# 3. Proper CORS configuration
# 4. Lambda permissions for API Gateway
#
# Usage:
#   ./setup_api_gateway_dynamic.sh
#
# Prerequisites:
#   - AWS CLI configured
#   - Appropriate IAM permissions
#   - Lambda code packaged (bedrock_api_lambda.py)
###############################################################################

set -e  # Exit on error

# Configuration
REGION="${AWS_REGION:-us-east-1}"
LAMBDA_FUNCTION_NAME="bedrock-api-dynamic-evaluation"
API_NAME="bedrock-groundtruth-dynamic-api"
STAGE_NAME="prod"
S3_BUCKET="${S3_BUCKET:-}"  # Optional: for response caching

# Read configuration from bedrock_config.json
CONFIG_FILE="$(dirname "$0")/bedrock_config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ ERROR: Config file not found: $CONFIG_FILE"
    exit 1
fi

BEDROCK_MODEL_ID=$(jq -r '.model_id' "$CONFIG_FILE")
KNOWLEDGE_BASE_ID=$(jq -r '.knowledge_base_id' "$CONFIG_FILE")

echo "========================================"
echo "Setting up API Gateway for Dynamic Evaluation"
echo "========================================"
echo ""
echo "Configuration:"
echo "  Region: $REGION"
echo "  Lambda Function: $LAMBDA_FUNCTION_NAME"
echo "  API Name: $API_NAME"
echo "  Stage: $STAGE_NAME"
echo "  S3 Cache Bucket: ${S3_BUCKET:-None (caching disabled)}"
echo ""

# Get AWS Account ID
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
echo "AWS Account ID: $ACCOUNT_ID"
echo ""

###############################################################################
# Step 1: Create IAM Role for Lambda
###############################################################################

echo "Step 1: Creating IAM role for Lambda..."

ROLE_NAME="BedrockApiDynamicLambdaRole"

# Check if role exists
if aws iam get-role --role-name $ROLE_NAME 2>/dev/null; then
    echo "  ℹ️  Role already exists: $ROLE_NAME"
else
    # Create trust policy
    cat > /tmp/trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "lambda.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    aws iam create-role \
        --role-name $ROLE_NAME \
        --assume-role-policy-document file:///tmp/trust-policy.json \
        --description "Role for Bedrock API Lambda in dynamic Ground Truth evaluation"

    echo "  ✅ Created role: $ROLE_NAME"
fi

# Create/update IAM policy
cat > /tmp/lambda-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:Retrieve",
        "bedrock:RetrieveAndGenerate"
      ],
      "Resource": [
        "arn:aws:bedrock:${REGION}::foundation-model/*",
        "arn:aws:bedrock:${REGION}:${ACCOUNT_ID}:knowledge-base/${KNOWLEDGE_BASE_ID}"
      ]
    }
EOF

# Add S3 permissions if bucket is provided
if [ -n "$S3_BUCKET" ]; then
    cat >> /tmp/lambda-policy.json <<EOF
    ,
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject"
      ],
      "Resource": "arn:aws:s3:::${S3_BUCKET}/*"
    }
EOF
fi

cat >> /tmp/lambda-policy.json <<EOF
  ]
}
EOF

aws iam put-role-policy \
    --role-name $ROLE_NAME \
    --policy-name BedrockApiDynamicPolicy \
    --policy-document file:///tmp/lambda-policy.json

echo "  ✅ Updated IAM policy"

ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
echo "  Role ARN: $ROLE_ARN"
echo ""

# Wait for role to propagate
echo "  ⏳ Waiting 10 seconds for IAM role to propagate..."
sleep 10

###############################################################################
# Step 2: Package and Deploy Lambda Function
###############################################################################

echo "Step 2: Packaging Lambda function..."

cd lambda

# Package lambda
zip -q bedrock_api_lambda.zip bedrock_api_lambda.py

echo "  ✅ Packaged: bedrock_api_lambda.zip"
echo ""

echo "Step 3: Deploying Lambda function..."

# Check if Lambda function exists
if aws lambda get-function --function-name $LAMBDA_FUNCTION_NAME --region $REGION 2>/dev/null; then
    echo "  ℹ️  Lambda function already exists, updating..."

    aws lambda update-function-code \
        --function-name $LAMBDA_FUNCTION_NAME \
        --zip-file fileb://bedrock_api_lambda.zip \
        --region $REGION

    aws lambda update-function-configuration \
        --function-name $LAMBDA_FUNCTION_NAME \
        --runtime python3.11 \
        --handler bedrock_api_lambda.lambda_handler \
        --timeout 60 \
        --memory-size 512 \
        --environment Variables="{KNOWLEDGE_BASE_ID=${KNOWLEDGE_BASE_ID},BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID},S3_CACHE_BUCKET=${S3_BUCKET},S3_CACHE_PREFIX=bedrock-cache/dynamic/}" \
        --region $REGION

    echo "  ✅ Updated Lambda function"
else
    aws lambda create-function \
        --function-name $LAMBDA_FUNCTION_NAME \
        --runtime python3.11 \
        --role $ROLE_ARN \
        --handler bedrock_api_lambda.lambda_handler \
        --zip-file fileb://bedrock_api_lambda.zip \
        --timeout 60 \
        --memory-size 512 \
        --environment Variables="{KNOWLEDGE_BASE_ID=${KNOWLEDGE_BASE_ID},BEDROCK_MODEL_ID=${BEDROCK_MODEL_ID},S3_CACHE_BUCKET=${S3_BUCKET},S3_CACHE_PREFIX=bedrock-cache/dynamic/}" \
        --region $REGION

    echo "  ✅ Created Lambda function"
fi

LAMBDA_ARN=$(aws lambda get-function --function-name $LAMBDA_FUNCTION_NAME --region $REGION --query 'Configuration.FunctionArn' --output text)
echo "  Lambda ARN: $LAMBDA_ARN"
echo ""

cd ..

###############################################################################
# Step 4: Create API Gateway
###############################################################################

echo "Step 4: Creating API Gateway..."

# Check if API exists
API_ID=$(aws apigateway get-rest-apis --region $REGION --query "items[?name=='${API_NAME}'].id" --output text)

if [ -z "$API_ID" ]; then
    API_ID=$(aws apigateway create-rest-api \
        --name $API_NAME \
        --description "API for dynamic Ground Truth Bedrock evaluation" \
        --region $REGION \
        --query 'id' \
        --output text)
    echo "  ✅ Created API: $API_ID"
else
    echo "  ℹ️  API already exists: $API_ID"
fi

# Get root resource ID
ROOT_RESOURCE_ID=$(aws apigateway get-resources --rest-api-id $API_ID --region $REGION --query 'items[?path==`/`].id' --output text)

# Create /generate-response resource if it doesn't exist
RESOURCE_ID=$(aws apigateway get-resources --rest-api-id $API_ID --region $REGION --query "items[?pathPart=='generate-response'].id" --output text)

if [ -z "$RESOURCE_ID" ]; then
    RESOURCE_ID=$(aws apigateway create-resource \
        --rest-api-id $API_ID \
        --parent-id $ROOT_RESOURCE_ID \
        --path-part generate-response \
        --region $REGION \
        --query 'id' \
        --output text)
    echo "  ✅ Created resource: /generate-response"
else
    echo "  ℹ️  Resource already exists: /generate-response"
fi

###############################################################################
# Step 5: Configure POST Method
###############################################################################

echo ""
echo "Step 5: Configuring POST method..."

# Create POST method
aws apigateway put-method \
    --rest-api-id $API_ID \
    --resource-id $RESOURCE_ID \
    --http-method POST \
    --authorization-type NONE \
    --region $REGION 2>/dev/null || echo "  ℹ️  POST method already exists"

# Set up Lambda integration
aws apigateway put-integration \
    --rest-api-id $API_ID \
    --resource-id $RESOURCE_ID \
    --http-method POST \
    --type AWS_PROXY \
    --integration-http-method POST \
    --uri "arn:aws:apigateway:${REGION}:lambda:path/2015-03-31/functions/${LAMBDA_ARN}/invocations" \
    --region $REGION

echo "  ✅ Configured POST method"

###############################################################################
# Step 6: Configure CORS (OPTIONS method)
###############################################################################

echo ""
echo "Step 6: Configuring CORS..."

# Create OPTIONS method
aws apigateway put-method \
    --rest-api-id $API_ID \
    --resource-id $RESOURCE_ID \
    --http-method OPTIONS \
    --authorization-type NONE \
    --region $REGION 2>/dev/null || echo "  ℹ️  OPTIONS method already exists"

# Set up MOCK integration for OPTIONS
aws apigateway put-integration \
    --rest-api-id $API_ID \
    --resource-id $RESOURCE_ID \
    --http-method OPTIONS \
    --type MOCK \
    --request-templates '{"application/json": "{\"statusCode\": 200}"}' \
    --region $REGION

# Set OPTIONS method response
aws apigateway put-method-response \
    --rest-api-id $API_ID \
    --resource-id $RESOURCE_ID \
    --http-method OPTIONS \
    --status-code 200 \
    --response-parameters '{"method.response.header.Access-Control-Allow-Headers":false,"method.response.header.Access-Control-Allow-Methods":false,"method.response.header.Access-Control-Allow-Origin":false}' \
    --region $REGION 2>/dev/null || true

# Set OPTIONS integration response
aws apigateway put-integration-response \
    --rest-api-id $API_ID \
    --resource-id $RESOURCE_ID \
    --http-method OPTIONS \
    --status-code 200 \
    --response-parameters '{"method.response.header.Access-Control-Allow-Headers":"'"'"'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"'"'","method.response.header.Access-Control-Allow-Methods":"'"'"'POST,OPTIONS'"'"'","method.response.header.Access-Control-Allow-Origin":"'"'"'*'"'"'"}' \
    --region $REGION 2>/dev/null || true

echo "  ✅ Configured CORS"

###############################################################################
# Step 7: Grant API Gateway Permission to Invoke Lambda
###############################################################################

echo ""
echo "Step 7: Granting API Gateway permission to invoke Lambda..."

# Add permission for API Gateway to invoke Lambda
aws lambda add-permission \
    --function-name $LAMBDA_FUNCTION_NAME \
    --statement-id apigateway-invoke-$(date +%s) \
    --action lambda:InvokeFunction \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${REGION}:${ACCOUNT_ID}:${API_ID}/*/*/*" \
    --region $REGION 2>/dev/null || echo "  ℹ️  Permission already exists"

echo "  ✅ Permission granted"

###############################################################################
# Step 8: Deploy API
###############################################################################

echo ""
echo "Step 8: Deploying API to ${STAGE_NAME} stage..."

aws apigateway create-deployment \
    --rest-api-id $API_ID \
    --stage-name $STAGE_NAME \
    --stage-description "Production stage for dynamic evaluation" \
    --description "Deployment $(date)" \
    --region $REGION

echo "  ✅ API deployed"

###############################################################################
# Summary
###############################################################################

API_ENDPOINT="https://${API_ID}.execute-api.${REGION}.amazonaws.com/${STAGE_NAME}/generate-response"

echo ""
echo "========================================"
echo "✅ Setup Complete!"
echo "========================================"
echo ""
echo "📋 Summary:"
echo "  Lambda Function: $LAMBDA_FUNCTION_NAME"
echo "  Lambda ARN: $LAMBDA_ARN"
echo "  API Gateway ID: $API_ID"
echo "  API Endpoint: $API_ENDPOINT"
echo ""
echo "🔧 Next Steps:"
echo ""
echo "1. Update the HTML template with the API endpoint:"
echo "   File: templates/retirement_coach_evaluation_template_dynamic.html"
echo "   Replace: const BEDROCK_API_ENDPOINT = '\${API_GATEWAY_URL}';"
echo "   With:    const BEDROCK_API_ENDPOINT = '${API_ENDPOINT}';"
echo ""
echo "2. Test the API endpoint:"
echo "   curl -X POST ${API_ENDPOINT} \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"question\":\"What is a pension?\"}'"
echo ""
echo "3. Upload the updated template to S3:"
echo "   aws s3 cp templates/retirement_coach_evaluation_template_dynamic.html \\"
echo "     s3://YOUR_BUCKET/groundtruth/templates/template_dynamic.html"
echo ""
echo "4. Create a Ground Truth labeling job using the dynamic template"
echo "   python config/create_groundtruth_job_dynamic.py"
echo ""
echo "========================================"

# Clean up temporary files
rm -f /tmp/trust-policy.json /tmp/lambda-policy.json

exit 0
