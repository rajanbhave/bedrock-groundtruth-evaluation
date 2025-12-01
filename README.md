# SageMaker Ground Truth Custom Workflow for Bedrock Model Evaluation

This project implements a complete custom workflow for human evaluation of Amazon Bedrock model responses using SageMaker Ground Truth, with structured feedback storage in Aurora PostgreSQL.

## Bedrock Integration

**Generate responses automatically during evaluation!** The pre-annotation Lambda now invokes Bedrock models on-demand, eliminating the need to pre-generate responses.

**Key Features:**
- On-the-fly vs pre-generated mode comparison
- Bedrock model configuration (Claude 3 Sonnet)
- S3 caching for cost optimization
- Comprehensive error handling and retry logic
- Performance benchmarking and monitoring

## 📋 Overview

This solution enables structured human evaluation of AI-generated retirement planning advice with:

- **Custom HTML UI** for rich evaluation experience with multiple rating dimensions
- **On-the-fly Bedrock invocation** (NEW) or pre-generated responses
- **Pre/Post-annotation Lambda functions** for Bedrock integration, data processing, and Aurora storage
- **Structured feedback storage** in Aurora PostgreSQL with comprehensive metrics
- **S3 caching** to optimize costs and reduce latency
- **Comprehensive evaluation metrics** including quality ratings, compliance checks, and detailed feedback

## 🏗️ Architecture

### On-the-Fly Mode (NEW - Recommended)
```
┌─────────────────┐
│  Question-Only  │ (JSONL in S3)
│  Dataset        │ (No responses needed!)
└────────┬────────┘
         │
         ▼
┌────────────────────────────────────────────────────────┐
│        SageMaker Ground Truth Labeling Job             │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Pre-Annotation Lambda (Enhanced)                │  │
│  │  • Invokes Bedrock API                           │  │
│  │  • S3 caching for duplicates                     │  │
│  │  • Retry logic & error handling                  │  │
│  └──────────────┬───────────────────────────────────┘  │
│                 │                                       │
│                 ▼                                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Custom HTML Template                            │  │
│  │  (Worker UI with ratings & feedback)             │  │
│  └──────────────┬───────────────────────────────────┘  │
│                 │                                       │
│                 ▼                                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │  Post-Annotation Lambda                          │  │
│  │  (Consolidate + Store in Aurora)                 │  │
│  └──────────────┬───────────────────────────────────┘  │
└─────────────────┼─────────────────────────────────────┘
                  │
         ┌────────┴────────┐
         │                 │
         ▼                 ▼
  ┌─────────────┐   ┌────────────────┐
  │   Bedrock   │   │    Aurora      │
  │   Models    │   │  PostgreSQL    │
  └─────────────┘   └────────────────┘
```

### Pre-Generated Mode
For cost optimization or when consistency is required, responses can be pre-generated using the batch generation script

## 📁 Project Structure

```
bedrock-groundtruth-evaluation/
├── README.md                                      # This file
├── templates/
│   └── retirement_coach_evaluation_template.html  # Custom HTML UI template
├── lambda/
│   ├── pre_annotation_lambda.py                   # Enhanced with Bedrock invocation (UPDATED)
│   ├── post_annotation_lambda.py                  # Post-processing + Aurora integration
│   ├── requirements.txt                           # Python dependencies
│   ├── package_lambda.sh                          # Original packaging script
│   └── deploy_lambda.sh                           # Enhanced deployment script (NEW)
├── config/
│   ├── bedrock_config.json                        # Bedrock model configuration (NEW)
│   ├── create_groundtruth_job.py                  # Job creation script
│   ├── aurora_schema.sql                          # Database schema
│   ├── test_bedrock_integration.py                # Bedrock integration test suite (NEW)
│   ├── batch_generate_responses.py                # Batch response generation (NEW)
│   ├── example_usage.py                           # Usage examples
│   └── cloudwatch_dashboard.json                  # CloudWatch monitoring dashboard (NEW)
├── datasets/
│   ├── sample_prompts.jsonl                       # Sample dataset with responses
│   └── sample_prompts_questions_only.jsonl        # Questions-only dataset (NEW)
└── iam-policies/
    ├── groundtruth-execution-role-policy.json     # Ground Truth IAM policy
    ├── groundtruth-execution-role-trust-policy.json
    ├── lambda-pre-annotation-policy.json          # With Bedrock permissions (UPDATED)
    ├── lambda-post-annotation-policy.json
    └── lambda-execution-role-trust-policy.json
```

## 🚀 Setup Guide

### Prerequisites

- AWS Account with access to:
  - SageMaker Ground Truth
  - AWS Lambda
  - Amazon S3
  - Aurora PostgreSQL
  - Amazon Bedrock (optional, for generating responses)
- AWS CLI configured with appropriate credentials
- Python 3.9 or later
- boto3 Python library

### Step 1: Create S3 Bucket

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

# Create pre-annotation Lambda
aws lambda create-function \
    --function-name groundtruth-pre-annotation-retirement-coach \
    --runtime python3.11 \
    --role arn:aws:iam::YOUR-ACCOUNT-ID:role/GroundTruthPreAnnotationLambdaRole \
    --handler pre_annotation_lambda.lambda_handler \
    --zip-file fileb://pre-annotation-lambda.zip \
    --timeout 60 \
    --memory-size 256

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

### Step 8: Upload Dataset and Template

```bash
# Upload sample dataset
aws s3 cp datasets/sample_prompts_questions_only.jsonl s3://${BUCKET_NAME}/groundtruth/input/prompts.jsonl

# Upload HTML template
aws s3 cp templates/retirement_coach_evaluation_template.html s3://${BUCKET_NAME}/groundtruth/templates/template.html
```

### Step 9: Create Ground Truth Labeling Job

```bash
# Using the Python script
python config/create_groundtruth_job.py \
    --job-name retirement-coach-eval-$(date +%Y%m%d-%H%M%S) \
    --input-manifest s3://${BUCKET_NAME}/groundtruth/input/prompts.jsonl \
    --output-path s3://${BUCKET_NAME}/groundtruth/output/ \
    --template-file templates/retirement_coach_evaluation_template.html \
    --template-s3-bucket ${BUCKET_NAME} \
    --role-arn ${GT_ROLE_ARN} \
    --workteam-arn ${WORKTEAM_ARN} \
    --pre-lambda-arn ${PRE_LAMBDA_ARN} \
    --post-lambda-arn ${POST_LAMBDA_ARN} \
    --workers-per-object 2

# Monitor job status
aws sagemaker describe-labeling-job --labeling-job-name retirement-coach-eval-20251120-213209
```

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
