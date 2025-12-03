#!/usr/bin/env python3
"""
Create SageMaker Ground Truth Labeling Job - Dynamic Question Version

This script creates a Ground Truth labeling job for DYNAMIC question evaluation where
workers provide their own questions and rate the AI responses.

Key differences from static version:
- Simplified manifest (just task IDs, no pre-defined questions)
- No pre-annotation Lambda needed (or it's a simple pass-through)
- Workers input questions via the HTML template
- Template calls API Gateway to get Bedrock responses
- Post-annotation Lambda receives question + response + rating from worker

Usage:
    python create_groundtruth_job_dynamic.py \\
        --job-name retirement-coach-dynamic-$(date +%Y%m%d-%H%M%S) \\
        --input-manifest s3://YOUR_BUCKET/groundtruth/input/dynamic_tasks.jsonl \\
        --output-path s3://YOUR_BUCKET/groundtruth/output/ \\
        --template-s3-uri s3://YOUR_BUCKET/groundtruth/templates/template_dynamic.html \\
        --role-arn arn:aws:iam::ACCOUNT:role/GroundTruthExecutionRole \\
        --workteam-arn arn:aws:sagemaker:us-east-1:ACCOUNT:workteam/private-crowd/NAME \\
        --post-lambda-arn arn:aws:lambda:us-east-1:ACCOUNT:function:post-annotation
"""

import boto3
import argparse
import sys
from datetime import datetime, timedelta

# Initialize SageMaker client
sagemaker = boto3.client('sagemaker', region_name='us-east-1')


def create_labeling_job(args):
    """
    Create SageMaker Ground Truth labeling job for dynamic evaluation.

    Args:
        args: Command line arguments
    """

    # Build labeling job configuration
    labeling_job_config = {
        'LabelingJobName': args.job_name,
        'LabelAttributeName': 'evaluation',
        'InputConfig': {
            'DataSource': {
                'S3DataSource': {
                    'ManifestS3Uri': args.input_manifest
                }
            }
        },
        'OutputConfig': {
            'S3OutputPath': args.output_path
        },
        'RoleArn': args.role_arn,
        'HumanTaskConfig': {
            'WorkteamArn': args.workteam_arn,
            'UiConfig': {
                'UiTemplateS3Uri': args.template_s3_uri
            },
            'PreHumanTaskLambdaArn': args.pre_lambda_arn if args.pre_lambda_arn else None,
            'TaskTitle': 'Dynamic Retirement Planning AI Evaluation',
            'TaskDescription': 'Ask your own question, receive an AI response, and evaluate its quality.',
            'NumberOfHumanWorkersPerDataObject': args.workers_per_object,
            'TaskTimeLimitInSeconds': args.task_timeout,
            'TaskAvailabilityLifetimeInSeconds': args.task_availability,
            'MaxConcurrentTaskCount': args.max_concurrent,
            'TaskKeywords': [
                'retirement',
                'pension',
                'AI evaluation',
                'quality assessment',
                'dynamic questions'
            ]
        },
        'Tags': [
            {'Key': 'Project', 'Value': 'BedrockEvaluation'},
            {'Key': 'Type', 'Value': 'DynamicQuestions'},
            {'Key': 'CreatedBy', 'Value': 'GroundTruthJobScript'},
            {'Key': 'CreatedAt', 'Value': datetime.now().isoformat()}
        ]
    }

    # Remove PreHumanTaskLambdaArn if not provided
    if not args.pre_lambda_arn:
        del labeling_job_config['HumanTaskConfig']['PreHumanTaskLambdaArn']

    # Add post-annotation Lambda if provided
    if args.post_lambda_arn:
        labeling_job_config['HumanTaskConfig']['AnnotationConsolidationConfig'] = {
            'AnnotationConsolidationLambdaArn': args.post_lambda_arn
        }

    # Create the labeling job
    try:
        print(f"Creating labeling job: {args.job_name}")
        print(f"  Input manifest: {args.input_manifest}")
        print(f"  Output path: {args.output_path}")
        print(f"  Template: {args.template_s3_uri}")
        print(f"  Workteam: {args.workteam_arn}")
        print(f"  Workers per object: {args.workers_per_object}")
        print(f"  Post-annotation Lambda: {args.post_lambda_arn if args.post_lambda_arn else 'None'}")
        print("")

        response = sagemaker.create_labeling_job(**labeling_job_config)

        print("✅ Labeling job created successfully!")
        print(f"  Job ARN: {response['LabelingJobArn']}")
        print("")
        print("📋 Job Details:")
        print(f"  Name: {args.job_name}")
        print(f"  Status: Check with 'aws sagemaker describe-labeling-job --labeling-job-name {args.job_name}'")
        print("")
        print("🌐 Worker Portal:")
        print("  Workers can access tasks at: https://WORKTEAM_ID.labeling.us-east-1.sagemaker.aws")
        print("  (The exact URL is in the SageMaker console under Ground Truth > Labeling workforces)")
        print("")
        print("💡 Next Steps:")
        print("  1. Verify job status in SageMaker console")
        print("  2. Workers log in to the portal")
        print("  3. Workers enter their own questions")
        print("  4. AI generates responses via API Gateway")
        print("  5. Workers evaluate and submit ratings")
        print("  6. Results stored in Aurora via post-annotation Lambda")
        print("")

        return response

    except Exception as e:
        print(f"❌ Error creating labeling job: {str(e)}")
        sys.exit(1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Create SageMaker Ground Truth labeling job for dynamic question evaluation',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic job creation
  python create_groundtruth_job_dynamic.py \\
    --job-name retirement-coach-dynamic-20251201 \\
    --input-manifest s3://my-bucket/groundtruth/input/dynamic_tasks.jsonl \\
    --output-path s3://my-bucket/groundtruth/output/ \\
    --template-s3-uri s3://my-bucket/groundtruth/templates/template_dynamic.html \\
    --role-arn arn:aws:iam::123456789012:role/GroundTruthExecutionRole \\
    --workteam-arn arn:aws:sagemaker:us-east-1:123456789012:workteam/private-crowd/evaluators \\
    --post-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:post-annotation

  # With custom settings
  python create_groundtruth_job_dynamic.py \\
    --job-name my-dynamic-job \\
    --input-manifest s3://my-bucket/input/tasks.jsonl \\
    --output-path s3://my-bucket/output/ \\
    --template-s3-uri s3://my-bucket/template.html \\
    --role-arn arn:aws:iam::123456789012:role/GTRole \\
    --workteam-arn arn:aws:sagemaker:us-east-1:123456789012:workteam/private-crowd/team \\
    --post-lambda-arn arn:aws:lambda:us-east-1:123456789012:function:post \\
    --workers-per-object 1 \\
    --task-timeout 3600 \\
    --max-concurrent 10
"""
    )

    # Required arguments
    parser.add_argument('--job-name', required=True,
                       help='Name for the labeling job (must be unique)')
    parser.add_argument('--input-manifest', required=True,
                       help='S3 URI of input manifest (JSONL file with task IDs)')
    parser.add_argument('--output-path', required=True,
                       help='S3 path for output (e.g., s3://bucket/output/)')
    parser.add_argument('--template-s3-uri', required=True,
                       help='S3 URI of HTML template for dynamic evaluation')
    parser.add_argument('--role-arn', required=True,
                       help='IAM role ARN for Ground Truth execution')
    parser.add_argument('--workteam-arn', required=True,
                       help='ARN of the private workteam')

    # Optional arguments
    parser.add_argument('--pre-lambda-arn',
                       help='Pre-annotation Lambda ARN (optional, usually not needed for dynamic)')
    parser.add_argument('--post-lambda-arn',
                       help='Post-annotation Lambda ARN for data storage (optional)')
    parser.add_argument('--workers-per-object', type=int, default=1,
                       help='Number of workers per task (default: 1)')
    parser.add_argument('--task-timeout', type=int, default=3600,
                       help='Task time limit in seconds (default: 3600 = 1 hour)')
    parser.add_argument('--task-availability', type=int, default=864000,
                       help='Task availability in seconds (default: 864000 = 10 days)')
    parser.add_argument('--max-concurrent', type=int, default=1000,
                       help='Max concurrent tasks (default: 1000)')

    args = parser.parse_args()

    # Validate arguments
    if not args.job_name:
        print("❌ Error: Job name is required")
        sys.exit(1)

    if not args.input_manifest.startswith('s3://'):
        print("❌ Error: Input manifest must be an S3 URI (s3://...)")
        sys.exit(1)

    if not args.output_path.startswith('s3://'):
        print("❌ Error: Output path must be an S3 URI (s3://...)")
        sys.exit(1)

    if not args.template_s3_uri.startswith('s3://'):
        print("❌ Error: Template URI must be an S3 URI (s3://...)")
        sys.exit(1)

    # Create the labeling job
    create_labeling_job(args)


if __name__ == '__main__':
    main()
