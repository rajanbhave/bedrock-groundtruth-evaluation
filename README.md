# SageMaker Ground Truth Custom Workflow for Bedrock Model Evaluation

This project implements a complete custom workflow for human evaluation of Amazon Bedrock model responses using SageMaker Ground Truth, with structured feedback storage in Aurora PostgreSQL.

## 🎯 Two Evaluation Approaches

This system supports **two distinct evaluation workflows** to accommodate different use cases:

### 📄 Static Version (Pre-defined Questions)
- **Best for**: Consistent evaluation of specific question sets, benchmarking, A/B testing
- **How it works**: Questions are pre-defined in the manifest, AI responses are generated before workers see them
- **Worker experience**: Workers see questions already populated with AI responses, focus on evaluation
- **Response generation**: Pre-annotation Lambda invokes Bedrock before task display
- **Use case**: "Evaluate how the AI handles these 50 specific retirement planning questions"

### ⚡ Dynamic Version (Worker-generated Questions)
- **Best for**: Exploratory testing, edge case discovery, realistic user scenarios
- **How it works**: Workers input their own questions, AI responds in real-time via API Gateway
- **Worker experience**: Workers type questions, click "Generate Response", then evaluate
- **Response generation**: Browser JavaScript calls API Gateway → Lambda → Bedrock (10-15 seconds)
- **Use case**: "Let evaluators explore how the AI handles unexpected pension questions"

## 📋 Overview

This solution enables structured human evaluation of AI-generated retirement planning advice with:

- **Custom HTML UI** for rich evaluation experience with multiple rating dimensions
- **Two evaluation modes**: Static (pre-defined) and Dynamic (worker-generated questions)
- **Bedrock Knowledge Base Integration**: RAG-powered responses grounded in UK pension documentation
- **Real-time and pre-generated response options** using Amazon Bedrock
- **Pre/Post-annotation Lambda functions** for data processing and Aurora storage
- **API Gateway integration** for dynamic real-time Bedrock invocation
- **Structured feedback storage** in Aurora PostgreSQL with comprehensive metrics
- **S3 caching** to optimize costs and reduce latency
- **Comprehensive evaluation metrics** including quality ratings, compliance checks, and detailed feedback

## 🧠 Knowledge Base Integration (RAG)

Both evaluation versions use **Amazon Bedrock Knowledge Base** with Retrieval Augmented Generation (RAG):

- **Knowledge Base**: Stores and indexes your UK pension documentation
- **RAG Process**: Questions → KB retrieves relevant docs → Claude generates response using context
- **Benefits**: More accurate, grounded responses based on your curated documentation
- **Configuration**: Knowledge Base ID stored in `config/bedrock_config.json`
- **Response Quality**: AI answers cite and reference official UK pension materials

## 🏗️ Architecture

### Static Version Architecture (Pre-defined Questions + RAG)
```
┌─────────────────────────┐
│  Static Manifest        │ (JSONL in S3)
│  {source, category,     │ Questions pre-defined
│   question}             │
└────────┬────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│            SageMaker Ground Truth Labeling Job               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Pre-Annotation Lambda                                 │  │
│  │  • Receives question from manifest                     │  │
│  │  • Queries Bedrock Knowledge Base (RAG)                │  │
│  │  • KB retrieves relevant UK pension docs               │  │
│  │  • Claude generates response with context              │  │
│  │  • Returns question + KB-grounded response             │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Static HTML Template                                  │  │
│  │  • Question already populated                          │  │
│  │  • AI response with KB context displayed               │  │
│  │  • Worker evaluates and rates                          │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Post-Annotation Lambda                                │  │
│  │  (Consolidate + Store in Aurora)                       │  │
│  └──────────────┬─────────────────────────────────────────┘  │
└─────────────────┼───────────────────────────────────────────┘
                  │
         ┌────────┴─────────────────┐
         │                          │
         ▼                          ▼
  ┌──────────────┐          ┌────────────────┐
  │   Bedrock    │          │    Aurora      │
  │ Knowledge    │◄────┐    │  PostgreSQL    │
  │     Base     │     │    └────────────────┘
  │   (RAG)      │     │
  └──────────────┘     │
         │             │
         ▼             │
  ┌──────────────┐     │
  │   Claude 3   │─────┘
  │   Sonnet     │
  └──────────────┘
```

### Dynamic Version Architecture (Worker-generated Questions)
```
┌─────────────────────────┐
│  Dynamic Manifest       │ (JSONL in S3)
│  {source: "task-001"}   │ Just task IDs
└─────────────────────────┘
         │
         ▼
┌──────────────────────────────────────────────────────────────┐
│            SageMaker Ground Truth Labeling Job               │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Dynamic HTML Template                                 │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │ 1. Worker enters question in text field         │  │  │
│  │  │ 2. Clicks "Generate AI Response" button          │  │  │
│  │  │ 3. JavaScript calls API Gateway                  │  │  │
│  │  └──────────────────┬───────────────────────────────┘  │  │
│  └───────────────────────┼────────────────────────────────┘  │
│                          │                                    │
│                          │ HTTPS Request                      │
│                          ▼                                    │
│       ┌──────────────────────────────────────────────┐       │
│       │        API Gateway                           │       │
│       │  POST /generate-response                     │       │
│       └──────────────────┬───────────────────────────┘       │
│                          │                                    │
│                          ▼                                    │
│       ┌──────────────────────────────────────────────┐       │
│       │   Bedrock API Lambda                         │       │
│       │   • Validates question                       │       │
│       │   • Queries Bedrock Knowledge Base (RAG)     │       │
│       │   • KB retrieves UK pension docs             │       │
│       │   • Claude generates response with context   │       │
│       │   • Returns KB-grounded response + metadata  │       │
│       └──────────────────┬───────────────────────────┘       │
│                          │                                    │
│                          │ JSON Response                      │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Dynamic HTML Template (continued)                     │  │
│  │  4. Displays AI response with KB context              │  │
│  │  5. Worker evaluates and rates                         │  │
│  │  6. Submits evaluation                                 │  │
│  └──────────────┬─────────────────────────────────────────┘  │
│                 │                                             │
│                 ▼                                             │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Post-Annotation Lambda (Shared)                       │  │
│  │  (Consolidate + Store in Aurora)                       │  │
│  └──────────────┬─────────────────────────────────────────┘  │
└─────────────────┼───────────────────────────────────────────┘
                  │
         ┌────────┴─────────────────┐
         │                          │
         ▼                          ▼
  ┌──────────────┐          ┌────────────────┐
  │   Bedrock    │          │    Aurora      │
  │ Knowledge    │◄────┐    │  PostgreSQL    │
  │     Base     │     │    └────────────────┘
  │   (RAG)      │     │
  └──────────────┘     │
         │             │
         ▼             │
  ┌──────────────┐     │
  │   Claude 3   │─────┘
  │   Sonnet     │
  └──────────────┘
```

### Key Architectural Differences

| Component | Static Version | Dynamic Version |
|-----------|----------------|-----------------|
| **Manifest** | Contains questions | Just task IDs |
| **Pre-annotation Lambda** | ✅ Generates responses | ❌ Not used |
| **API Gateway** | ❌ Not used | ✅ Exposes Bedrock endpoint |
| **Bedrock API Lambda** | ❌ Not used | ✅ Handles real-time calls |
| **Response timing** | Before worker sees task | After worker enters question |
| **Worker input** | No question entry | Question text field |
| **Network calls** | Server-side only | Browser → API Gateway |
| **Post-annotation Lambda** | ✅ Shared | ✅ Shared |

## 📁 Project Structure

```
bedrock-groundtruth-evaluation/
├── README.md                                            # This file
├── VALIDATION_REPORT.md                                 # Dynamic version validation report
├── templates/
│   ├── retirement_coach_evaluation_template.html        # Static version HTML template
│   └── retirement_coach_evaluation_template_dynamic.html # Dynamic version HTML template (NEW)
├── lambda/
│   ├── pre_annotation_lambda.py                         # Pre-annotation Lambda (Static version)
│   ├── post_annotation_lambda.py                        # Post-processing + Aurora (Shared)
│   ├── bedrock_api_lambda.py                            # API Gateway Lambda (Dynamic version - NEW)
│   ├── requirements.txt                                 # Python dependencies
│   ├── package_lambda.sh                                # Lambda packaging script
│   └── deploy_lambda.sh                                 # Enhanced deployment script
├── config/
│   ├── bedrock_config.json                              # Bedrock model configuration
│   ├── create_groundtruth_job.py                        # Static version job creation
│   ├── create_groundtruth_job_dynamic.py                # Dynamic version job creation (NEW)
│   ├── setup_api_gateway_dynamic.sh                     # API Gateway deployment script (NEW)
│   ├── aurora_schema.sql                                # Database schema
│   ├── batch_generate_responses.py                      # Batch response generation
│   ├── create_workteam.sh                               # Workteam creation script
│   ├── workteam-members.json                            # Workteam member configuration
│   └── cloudwatch_dashboard.json                        # CloudWatch monitoring dashboard
├── datasets/
│   ├── sample_prompts_questions_only.jsonl              # Static version manifest (with questions)
│   └── dynamic_tasks.jsonl                              # Dynamic version manifest (task IDs only - NEW)
└── iam-policies/
    ├── groundtruth-execution-role-policy.json           # Ground Truth IAM policy
    ├── groundtruth-execution-role-trust-policy.json
    ├── lambda-pre-annotation-policy.json                # Static version Lambda policy
    ├── lambda-post-annotation-policy.json               # Shared post-annotation policy
    └── lambda-execution-role-trust-policy.json
```

### Version-Specific Files

**Static Version Files:**
- `templates/retirement_coach_evaluation_template.html`
- `lambda/pre_annotation_lambda.py`
- `config/create_groundtruth_job.py`
- `datasets/sample_prompts_questions_only.jsonl`

**Dynamic Version Files:**
- `templates/retirement_coach_evaluation_template_dynamic.html`
- `lambda/bedrock_api_lambda.py`
- `config/create_groundtruth_job_dynamic.py`
- `config/setup_api_gateway_dynamic.sh`
- `datasets/dynamic_tasks.jsonl`

**Shared Files:**
- `lambda/post_annotation_lambda.py` (both versions use same Aurora storage)
- `config/aurora_schema.sql` (database schema for both)
- All IAM policies and configuration files

## 🚀 Setup Guide

### Prerequisites

- AWS Account with access to:
  - SageMaker Ground Truth
  - AWS Lambda
  - Amazon S3
  - Aurora PostgreSQL
  - **Amazon Bedrock Knowledge Base** (required for RAG)
  - Amazon Bedrock (Claude 3 Sonnet model access)
- AWS CLI configured with appropriate credentials
- Python 3.9 or later
- boto3 Python library
- `jq` command-line JSON processor (for deployment scripts)

### Step 1: Configure Bedrock Knowledge Base

**IMPORTANT**: Both evaluation versions require a Bedrock Knowledge Base for RAG.

```bash
# Configure your Knowledge Base ID in bedrock_config.json
cd config
```

Edit `bedrock_config.json` and set your Knowledge Base ID:
```json
{
  "knowledge_base_id": "YOUR-KB-ID-HERE",
  "knowledge_base_name": "your-kb-name",
  "model_id": "anthropic.claude-3-sonnet-20240229-v1:0",
  ...
}
```

**How to find your Knowledge Base ID:**
```bash
# List your Knowledge Bases
aws bedrock-agent list-knowledge-bases --region us-east-1

# Or in the AWS Console:
# Navigate to Amazon Bedrock → Knowledge bases → Select your KB → Copy the ID
```

**Example Configuration:**
```json
{
  "knowledge_base_id": "UGAJVE9OPE",
  "knowledge_base_name": "uk-pension-knowledge-base-opensearch",
  "model_id": "anthropic.claude-3-sonnet-20240229-v1:0"
}
```

### Step 2: Create S3 Bucket

```bash
# Create S3 bucket for Ground Truth data
export BUCKET_NAME="your-groundtruth-bucket"
export AWS_REGION="us-east-1"

aws s3 mb s3://${BUCKET_NAME} --region ${AWS_REGION}

# Create folder structure
aws s3api put-object --bucket ${BUCKET_NAME} --key uk_pension_data/groundtruth/input/
aws s3api put-object --bucket ${BUCKET_NAME} --key uk_pension_data/groundtruth/output/
aws s3api put-object --bucket ${BUCKET_NAME} --key uk_pension_data/groundtruth/templates/
```

### Step 2: Configure S3 CORS for Ground Truth Console

```bash
# Create CORS configuration file
cat > cors-config.json << EOF
{
  "CORSRules": [
    {
      "AllowedOrigins": ["https://console.aws.amazon.com"],
      "AllowedMethods": ["GET", "PUT", "POST"],
      "AllowedHeaders": ["*"],
      "ExposeHeaders": ["ETag"],
      "MaxAgeSeconds": 3000
    }
  ]
}
EOF

# Apply CORS configuration
aws s3api put-bucket-cors --bucket ${BUCKET_NAME} --cors-configuration file://cors-config.json
```

### Step 3: Set Up Aurora PostgreSQL

```bash
# Create Aurora PostgreSQL cluster (adjust parameters as needed)
aws rds create-db-cluster \
    --db-cluster-identifier groundtruth-evaluations \
    --engine aurora-postgresql \
    --master-username postgres \
    --master-user-password YourSecurePassword123! \
    --database-name evaluations \
    --vpc-security-group-ids sg-xxxxx \
    --db-subnet-group-name your-subnet-group

# Create database instance (using smallest instance for cost optimization)
# For production, consider db.r6g.large or Aurora Serverless v2
aws rds create-db-instance \
    --db-instance-identifier groundtruth-evaluations-instance \
    --db-cluster-identifier groundtruth-evaluations \
    --db-instance-class db.t3.medium \
    --engine aurora-postgresql

# Wait for cluster to be available
aws rds wait db-cluster-available --db-cluster-identifier groundtruth-evaluations

# Connect and create schema
psql -h YOUR_AURORA_ENDPOINT.region.rds.amazonaws.com -U postgres -d evaluations -f config/aurora_schema.sql
```

### Step 4: Store Database Credentials in Secrets Manager

```bash
# Create secret for database credentials
aws secretsmanager create-secret \
    --name aurora-postgres-credentials \
    --description "Aurora PostgreSQL credentials for Ground Truth evaluation storage" \
    --secret-string '{
        "username":"postgres",
        "password":"YourSecurePassword123!",
        "host":"YOUR_AURORA_ENDPOINT.region.rds.amazonaws.com",
        "port":5432,
        "dbname":"evaluations"
    }'
```

### Step 5: Create IAM Roles

#### Ground Truth Execution Role

```bash
# Create trust policy
aws iam create-role \
    --role-name GroundTruthExecutionRole \
    --assume-role-policy-document file://iam-policies/groundtruth-execution-role-trust-policy.json

# Update the policy file with your bucket name
sed -i '' "s/YOUR-BUCKET-NAME/${BUCKET_NAME}/g" iam-policies/groundtruth-execution-role-policy.json

# Attach policy
aws iam put-role-policy \
    --role-name GroundTruthExecutionRole \
    --policy-name GroundTruthExecutionPolicy \
    --policy-document file://iam-policies/groundtruth-execution-role-policy.json

# Get role ARN
export GT_ROLE_ARN=$(aws iam get-role --role-name GroundTruthExecutionRole --query 'Role.Arn' --output text)
echo "Ground Truth Role ARN: ${GT_ROLE_ARN}"
```

#### Lambda Execution Roles

```bash
# Pre-annotation Lambda role
aws iam create-role \
    --role-name GroundTruthPreAnnotationLambdaRole \
    --assume-role-policy-document file://iam-policies/lambda-execution-role-trust-policy.json

sed -i '' "s/YOUR-BUCKET-NAME/${BUCKET_NAME}/g" iam-policies/lambda-pre-annotation-policy.json

aws iam put-role-policy \
    --role-name GroundTruthPreAnnotationLambdaRole \
    --policy-name PreAnnotationPolicy \
    --policy-document file://iam-policies/lambda-pre-annotation-policy.json

# Post-annotation Lambda role
aws iam create-role \
    --role-name GroundTruthPostAnnotationLambdaRole \
    --assume-role-policy-document file://iam-policies/lambda-execution-role-trust-policy.json

sed -i '' "s/YOUR-BUCKET-NAME/${BUCKET_NAME}/g" iam-policies/lambda-post-annotation-policy.json

aws iam put-role-policy \
    --role-name GroundTruthPostAnnotationLambdaRole \
    --policy-name PostAnnotationPolicy \
    --policy-document file://iam-policies/lambda-post-annotation-policy.json
```

### Step 6: Create and Deploy Lambda Functions

```bash
# Package Lambda functions
cd lambda
./package_lambda.sh

# Read Knowledge Base ID from config
KB_ID=$(jq -r '.knowledge_base_id' ../config/bedrock_config.json)
MODEL_ID=$(jq -r '.model_id' ../config/bedrock_config.json)

echo "Using Knowledge Base ID: $KB_ID"
echo "Using Model: $MODEL_ID"

# Create pre-annotation Lambda with Knowledge Base configuration
aws lambda create-function \
    --function-name groundtruth-pre-annotation-retirement-coach \
    --runtime python3.11 \
    --role arn:aws:iam::YOUR-ACCOUNT-ID:role/GroundTruthPreAnnotationLambdaRole \
    --handler pre_annotation_lambda.lambda_handler \
    --zip-file fileb://pre-annotation-lambda.zip \
    --timeout 60 \
    --memory-size 512 \
    --environment Variables="{KNOWLEDGE_BASE_ID=${KB_ID},BEDROCK_MODEL_ID=${MODEL_ID},MAX_TOKENS=2000,TEMPERATURE=0.7}"

# Create post-annotation Lambda
aws lambda create-function \
    --function-name groundtruth-post-annotation-retirement-coach \
    --runtime python3.11 \
    --role arn:aws:iam::YOUR-ACCOUNT-ID:role/GroundTruthPostAnnotationLambdaRole \
    --handler post_annotation_lambda.lambda_handler \
    --zip-file fileb://post-annotation-lambda.zip \
    --timeout 300 \
    --memory-size 512 \
    --environment Variables="{DB_SECRET_NAME=aurora-postgres-credentials-latest}" \
    --vpc-config SubnetIds=subnet-xxxxx,subnet-yyyyy,SecurityGroupIds=sg-zzzzz

# Get Lambda ARNs
export PRE_LAMBDA_ARN=$(aws lambda get-function --function-name groundtruth-pre-annotation-retirement-coach --query 'Configuration.FunctionArn' --output text)
export POST_LAMBDA_ARN=$(aws lambda get-function --function-name groundtruth-post-annotation-retirement-coach --query 'Configuration.FunctionArn' --output text)

echo "Pre-annotation Lambda ARN: ${PRE_LAMBDA_ARN}"
echo "Post-annotation Lambda ARN: ${POST_LAMBDA_ARN}"
```

**Note**: The pre-annotation Lambda requires:
- `KNOWLEDGE_BASE_ID`: Read from `bedrock_config.json`
- `BEDROCK_MODEL_ID`: Model to use for generation
- IAM permissions for `bedrock:RetrieveAndGenerate`

### Step 7: Create Private Workforce

```bash
# Create private work team using SageMaker console or CLI
# Note: This requires Cognito user pool setup

aws sagemaker create-workteam \
    --workteam-name retirement-coach-evaluators \
    --member-definitions file://workteam-members.json \
    --description "Private workforce for evaluating retirement planning model responses"

# Get workteam ARN
export WORKTEAM_ARN=$(aws sagemaker describe-workteam --workteam-name retirement-coach-evaluators --query 'Workteam.WorkteamArn' --output text)
echo "Workteam ARN: ${WORKTEAM_ARN}"
```

### Step 8: Choose Your Evaluation Version

At this point, choose which version(s) to deploy:

---

## 📄 Static Version Deployment (Pre-defined Questions)

### Step 8-Static: Upload Dataset and Template

```bash
# Upload static dataset (with questions)
aws s3 cp datasets/sample_prompts_questions_only.jsonl \
    s3://${BUCKET_NAME}/uk_pension_data/groundtruth/input/prompts.jsonl

# Upload static HTML template
aws s3 cp templates/retirement_coach_evaluation_template.html \
    s3://${BUCKET_NAME}/uk_pension_data/groundtruth/templates/template.html
```

### Step 9-Static: Create Static Labeling Job

```bash
# Create static labeling job with pre-defined questions
python config/create_groundtruth_job.py \
    --job-name retirement-coach-static-$(date +%Y%m%d-%H%M%S) \
    --input-manifest s3://${BUCKET_NAME}/uk_pension_data/groundtruth/input/prompts.jsonl \
    --output-path s3://${BUCKET_NAME}/uk_pension_data/groundtruth/output/ \
    --template-file templates/retirement_coach_evaluation_template.html \
    --template-s3-bucket ${BUCKET_NAME} \
    --role-arn ${GT_ROLE_ARN} \
    --workteam-arn ${WORKTEAM_ARN} \
    --pre-lambda-arn ${PRE_LAMBDA_ARN} \
    --post-lambda-arn ${POST_LAMBDA_ARN} \
    --workers-per-object 1

# Monitor job status
aws sagemaker describe-labeling-job --labeling-job-name retirement-coach-static-YYYYMMDD-HHMMSS
```

---

## ⚡ Dynamic Version Deployment (Worker-generated Questions)

### Step 8-Dynamic: Deploy API Gateway Infrastructure

```bash
# Deploy API Gateway + Lambda for dynamic Bedrock invocation
# The script automatically reads Knowledge Base ID from config/bedrock_config.json
./config/setup_api_gateway_dynamic.sh

# This script will:
# 1. Read Knowledge Base ID from bedrock_config.json
# 2. Create IAM role with bedrock:RetrieveAndGenerate permissions
# 3. Deploy bedrock-api-dynamic-evaluation Lambda with KB configuration
# 4. Create API Gateway REST API with CORS support
# 5. Output the API Gateway endpoint URL

# Save the API endpoint URL shown at the end - you'll need it for the next step
export API_ENDPOINT="<your-api-gateway-url>"  # Example: https://abc123.execute-api.us-east-1.amazonaws.com/prod/generate-response
```

**Note**: The dynamic Lambda also uses Knowledge Base RAG:
- Knowledge Base ID read from `config/bedrock_config.json`
- IAM role includes `bedrock:RetrieveAndGenerate` permission
- Responses grounded in your UK pension documentation

### Step 9-Dynamic: Update Template with API Endpoint

```bash
# Update the dynamic template with your API Gateway endpoint
# Edit templates/retirement_coach_evaluation_template_dynamic.html
# Find line with: const BEDROCK_API_ENDPOINT = 'https://...'
# Replace with your actual API endpoint URL from Step 8-Dynamic

# Or use sed:
sed -i '' "s|https://.*amazonaws.com/prod/generate-response|${API_ENDPOINT}|" \
    templates/retirement_coach_evaluation_template_dynamic.html
```

### Step 10-Dynamic: Upload Dynamic Files

```bash
# Upload dynamic dataset (just task IDs)
aws s3 cp datasets/dynamic_tasks.jsonl \
    s3://${BUCKET_NAME}/uk_pension_data/groundtruth/input/dynamic_tasks.jsonl

# Upload dynamic HTML template (with API endpoint configured)
aws s3 cp templates/retirement_coach_evaluation_template_dynamic.html \
    s3://${BUCKET_NAME}/uk_pension_data/groundtruth/templates/template_dynamic.html
```

### Step 11-Dynamic: Create Dynamic Labeling Job

```bash
# Create dynamic labeling job for worker-generated questions
python config/create_groundtruth_job_dynamic.py \
    --job-name retirement-coach-dynamic-$(date +%Y%m%d-%H%M%S) \
    --input-manifest s3://${BUCKET_NAME}/uk_pension_data/groundtruth/input/dynamic_tasks.jsonl \
    --output-path s3://${BUCKET_NAME}/uk_pension_data/groundtruth/output/ \
    --template-s3-uri s3://${BUCKET_NAME}/uk_pension_data/groundtruth/templates/template_dynamic.html \
    --role-arn ${GT_ROLE_ARN} \
    --workteam-arn ${WORKTEAM_ARN} \
    --post-lambda-arn ${POST_LAMBDA_ARN}

# Note: No pre-lambda-arn needed for dynamic version!

# Monitor job status
aws sagemaker describe-labeling-job --labeling-job-name retirement-coach-dynamic-YYYYMMDD-HHMMSS
```

---

## 🔍 Accessing the Worker Portal

Both versions use the same worker portal:

```bash
# Get worker portal URL
aws sagemaker describe-workteam --workteam-name retirement-coach-evaluators \
    --query 'Workteam.SubDomain' --output text

# Example output: https://abc123.labeling.us-east-1.sagemaker.aws
```

Workers will see:
- **Static tasks**: Questions already populated, AI responses pre-generated
- **Dynamic tasks**: Empty question field, "Generate AI Response" button

## 📊 Custom HTML Template Features

The evaluation template (`retirement_coach_evaluation_template.html`) provides:

### Rating Dimensions
- **Overall Quality** (1-5 scale with labels)
- **Accuracy & Factual Correctness** (slider)
- **Relevance** (slider)
- **Completeness** (slider)
- **Tone & Style** (slider)
- **Clarity** (slider)

### Compliance Checks
- Personalized financial advice without disclaimers
- Specific product recommendations
- Tax advice
- Legal advice
- Guarantee claims
- Misleading information

### Free-Text Feedback
- Overall written feedback
- Compliance notes
- Improvement suggestions

### Binary Assessments
- Production approval (Yes/No/Maybe)
- Preference over reference response

## 💾 Database Schema

The Aurora PostgreSQL database stores:

### `human_evaluations` table
- Consolidated ratings from all workers
- Average scores across dimensions
- Compliance violation tracking
- Approval statistics
- Metadata and timestamps

### `worker_feedback` table
- Individual worker feedback
- Detailed text annotations
- Worker-specific assessments

### Views
- `evaluation_summary`: Statistics by category
- `problematic_responses`: Low-quality or non-compliant responses
- `high_quality_responses`: High-performing responses

### Functions
- `get_evaluation_stats()`: Statistics by date range
- `get_worker_stats()`: Worker performance metrics

## 📈 Monitoring and Analysis

### View Job Progress

```bash
# Check job status
aws sagemaker describe-labeling-job --labeling-job-name your-job-name

# View CloudWatch logs
aws logs tail /aws/sagemaker/LabelingJobs --follow
```

### Query Evaluation Results

```sql
-- Get summary by category
SELECT * FROM evaluation_summary;

-- Find problematic responses
SELECT * FROM problematic_responses LIMIT 10;

-- Get high-quality examples
SELECT * FROM high_quality_responses WHERE category = 'Retirement Savings';

-- Evaluation stats for last 7 days
SELECT * FROM get_evaluation_stats(NOW() - INTERVAL '7 days', NOW());

-- Find responses with specific violations
SELECT prompt_id, question, compliance_violations
FROM human_evaluations
WHERE compliance_violations @> '["personalized_advice"]'::jsonb;
```

## 🔄 Integration with Bedrock

### Option 1: Pre-generate Responses

Generate responses using Bedrock before creating the dataset:

```python
import boto3
import json

bedrock = boto3.client('bedrock-runtime')

def generate_response(question):
    response = bedrock.invoke_model(
        modelId='anthropic.claude-3-sonnet-20240229-v1:0',
        body=json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 1000,
            "messages": [{"role": "user", "content": question}]
        })
    )
    return json.loads(response['body'].read())['content'][0]['text']

# Add to JSONL dataset
```

### Option 2: Generate On-the-Fly

Modify the pre-annotation Lambda to invoke Bedrock:

```python
# Uncomment the invoke_bedrock_model() function in pre_annotation_lambda.py
response_text = invoke_bedrock_model(question)
```

## 🔐 Security Best Practices

1. **IAM Roles**: Use least-privilege IAM policies
2. **VPC**: Deploy Lambda functions in VPC for Aurora access
3. **Secrets Manager**: Store database credentials securely
4. **Encryption**: Enable S3 bucket encryption and Aurora encryption at rest
5. **Private Workforce**: Use private workforce for sensitive data
6. **Audit Logging**: Enable CloudTrail for API call auditing

## 💰 Cost Optimization

- Use **on-demand pricing** for small evaluation jobs
- Consider **private workforce** vs. Mechanical Turk based on data sensitivity
- Set appropriate **task timeout limits** to prevent excessive charges
- Use **S3 lifecycle policies** to archive old evaluation data

## 🐛 Troubleshooting

### Common Issues

**Issue**: Lambda timeout in post-annotation function
- **Solution**: Increase timeout to 300 seconds and memory to 512 MB

**Issue**: Workers can't access the labeling portal
- **Solution**: Check Cognito user pool configuration and email verification

**Issue**: Database connection errors
- **Solution**: Verify Lambda VPC configuration and security groups

**Issue**: Template not rendering correctly
- **Solution**: Validate HTML syntax and check S3 CORS configuration

## 📚 Additional Resources

- [SageMaker Ground Truth Documentation](https://docs.aws.amazon.com/sagemaker/latest/dg/sms.html)
- [Custom Labeling Workflows](https://docs.aws.amazon.com/sagemaker/latest/dg/sms-custom-templates.html)
- [Bedrock Model Evaluation](https://docs.aws.amazon.com/bedrock/latest/userguide/model-evaluation.html)
- [Crowd HTML Elements Reference](https://docs.aws.amazon.com/sagemaker/latest/dg/sms-ui-template-reference.html)

## 📝 License

This project is provided as-is for demonstration purposes.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

---

**Next Steps**: After setup, monitor your first labeling job and review results in Aurora PostgreSQL. Use the evaluation data to improve your Bedrock prompts and model selection.
