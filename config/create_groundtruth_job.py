"""
Script to create a SageMaker Ground Truth labeling job with custom template
for human evaluation of Bedrock model responses.
"""

import boto3
import json
import argparse
from datetime import datetime


def create_labeling_job(
        job_name: str,
        input_manifest_s3_uri: str,
        output_s3_uri: str,
        task_template_s3_uri: str,
        role_arn: str,
        workteam_arn: str,
        pre_lambda_arn: str = None,
        post_lambda_arn: str = None,
        task_title: str = "Evaluate Retirement Planning Model Responses",
        task_description: str = "Assess the quality, compliance, and helpfulness of AI-generated retirement planning advice",
        num_workers_per_object: int = 1,
        task_time_limit_seconds: int = 3600
):
    """
    Create a Ground Truth labeling job.

    Args:
        job_name: Unique name for the labeling job
        input_manifest_s3_uri: S3 URI to the input manifest file (JSONL)
        output_s3_uri: S3 URI for the output location
        task_template_s3_uri: S3 URI to the custom HTML template
        role_arn: IAM role ARN for Ground Truth execution
        workteam_arn: Work team ARN for the labeling workforce
        pre_lambda_arn: Optional pre-annotation Lambda function ARN
        post_lambda_arn: Optional post-annotation Lambda function ARN
        task_title: Title shown to workers
        task_description: Description shown to workers
        num_workers_per_object: Number of workers to annotate each object
        task_time_limit_seconds: Time limit for each task (default: 1 hour)

    Returns:
        Response from CreateLabelingJob API
    """

    sagemaker = boto3.client('sagemaker')

    # Prepare the job configuration
    labeling_job_config = {
        'LabelingJobName': job_name,
        'LabelAttributeName': 'evaluation-result',
        'InputConfig': {
            'DataSource': {
                'S3DataSource': {
                    'ManifestS3Uri': input_manifest_s3_uri
                }
            }
        },
        'OutputConfig': {
            'S3OutputPath': output_s3_uri
        },
        'RoleArn': role_arn,
        'HumanTaskConfig': {
            'WorkteamArn': workteam_arn,
            'UiConfig': {
                'UiTemplateS3Uri': task_template_s3_uri
            },
            'TaskTitle': task_title,
            'TaskDescription': task_description,
            'NumberOfHumanWorkersPerDataObject': num_workers_per_object,
            'TaskTimeLimitInSeconds': task_time_limit_seconds,
            'TaskAvailabilityLifetimeInSeconds': 864000,  # 10 days
            'MaxConcurrentTaskCount': 1000
        },
        'Tags': [
            {
                'Key': 'Project',
                'Value': 'RetirementCoachEvaluation'
            },
            {
                'Key': 'Environment',
                'Value': 'Production'
            },
            {
                'Key': 'CreatedBy',
                'Value': 'GroundTruthAutomation'
            }
        ]
    }

    # Add pre-annotation Lambda if provided
    if pre_lambda_arn:
        labeling_job_config['HumanTaskConfig']['PreHumanTaskLambdaArn'] = pre_lambda_arn

    # Add post-annotation Lambda if provided (inside HumanTaskConfig)
    if post_lambda_arn:
        labeling_job_config['HumanTaskConfig']['AnnotationConsolidationConfig'] = {
            'AnnotationConsolidationLambdaArn': post_lambda_arn
        }

    try:
        print(f"Creating labeling job: {job_name}")
        print(f"Input manifest: {input_manifest_s3_uri}")
        print(f"Output location: {output_s3_uri}")
        print(f"Template: {task_template_s3_uri}")
        print(f"Work team: {workteam_arn}")
        print(f"Workers per object: {num_workers_per_object}")

        response = sagemaker.create_labeling_job(**labeling_job_config)

        print(f"\n✓ Labeling job created successfully!")
        print(f"Job ARN: {response['LabelingJobArn']}")
        print(f"\nMonitor the job in the AWS Console:")
        print(f"https://console.aws.amazon.com/sagemaker/groundtruth?#/labeling-jobs/{job_name}")

        return response

    except Exception as e:
        print(f"\n✗ Error creating labeling job: {str(e)}")
        raise


def create_workteam(
        workteam_name: str,
        worker_emails: list,
        description: str = "Private workforce for retirement coach evaluation"
):
    """
    Create a private work team for Ground Truth.

    Args:
        workteam_name: Name for the work team
        worker_emails: List of worker email addresses
        description: Description of the work team

    Returns:
        Work team ARN
    """

    sagemaker = boto3.client('sagemaker')

    try:
        # First, create a private workforce if it doesn't exist
        try:
            cognito_client = boto3.client('cognito-idp')

            # Create Cognito user pool for the workforce
            print("Creating Cognito user pool for private workforce...")

            user_pool_response = cognito_client.create_user_pool(
                PoolName=f'{workteam_name}-user-pool',
                AutoVerifiedAttributes=['email'],
                Policies={
                    'PasswordPolicy': {
                        'MinimumLength': 8,
                        'RequireUppercase': True,
                        'RequireLowercase': True,
                        'RequireNumbers': True,
                        'RequireSymbols': False
                    }
                }
            )

            user_pool_id = user_pool_response['UserPool']['Id']

            # Create user pool client
            client_response = cognito_client.create_user_pool_client(
                UserPoolId=user_pool_id,
                ClientName=f'{workteam_name}-client',
                GenerateSecret=False
            )

            client_id = client_response['UserPoolClient']['ClientId']

            print(f"Created Cognito user pool: {user_pool_id}")

        except Exception as e:
            print(f"Note: Private workforce may already exist: {str(e)}")

        # Create the work team
        print(f"Creating work team: {workteam_name}")

        workteam_response = sagemaker.create_workteam(
            WorkteamName=workteam_name,
            MemberDefinitions=[
                {
                    'CognitoMemberDefinition': {
                        'UserPool': user_pool_id,
                        'UserGroup': 'evaluators',
                        'ClientId': client_id
                    }
                }
            ],
            Description=description,
            NotificationConfiguration={
                'NotificationTopicArn': ''  # Optional: Add SNS topic for notifications
            }
        )

        workteam_arn = workteam_response['Workteam']['WorkteamArn']

        print(f"✓ Work team created: {workteam_arn}")

        # Add workers to the team
        for email in worker_emails:
            try:
                cognito_client.admin_create_user(
                    UserPoolId=user_pool_id,
                    Username=email,
                    UserAttributes=[
                        {'Name': 'email', 'Value': email},
                        {'Name': 'email_verified', 'Value': 'true'}
                    ],
                    DesiredDeliveryMediums=['EMAIL']
                )
                print(f"  Added worker: {email}")
            except Exception as e:
                print(f"  Note: Could not add {email}: {str(e)}")

        return workteam_arn

    except Exception as e:
        print(f"Error creating work team: {str(e)}")
        raise


def upload_template_to_s3(template_file_path: str, s3_bucket: str, s3_key: str):
    """
    Upload the custom HTML template to S3.

    Args:
        template_file_path: Local path to the HTML template file
        s3_bucket: S3 bucket name
        s3_key: S3 key (path) for the template

    Returns:
        S3 URI of the uploaded template
    """

    s3 = boto3.client('s3')

    try:
        with open(template_file_path, 'r') as f:
            template_content = f.read()

        s3.put_object(
            Bucket=s3_bucket,
            Key=s3_key,
            Body=template_content,
            ContentType='text/html'
        )

        s3_uri = f's3://{s3_bucket}/{s3_key}'
        print(f"✓ Template uploaded to: {s3_uri}")

        return s3_uri

    except Exception as e:
        print(f"Error uploading template: {str(e)}")
        raise


def main():
    parser = argparse.ArgumentParser(
        description='Create a SageMaker Ground Truth labeling job for Bedrock model evaluation'
    )

    parser.add_argument('--job-name', required=True, help='Name for the labeling job')
    parser.add_argument('--input-manifest', required=True, help='S3 URI to input manifest (JSONL)')
    parser.add_argument('--output-path', required=True, help='S3 URI for output location')
    parser.add_argument('--template-file', required=True, help='Local path to HTML template file')
    parser.add_argument('--template-s3-bucket', required=True, help='S3 bucket for template upload')
    parser.add_argument('--role-arn', required=True, help='IAM role ARN for Ground Truth')
    parser.add_argument('--workteam-arn', required=True, help='Work team ARN')
    parser.add_argument('--pre-lambda-arn', help='Pre-annotation Lambda ARN (optional)')
    parser.add_argument('--post-lambda-arn', help='Post-annotation Lambda ARN (optional)')
    parser.add_argument('--workers-per-object', type=int, default=1, help='Number of workers per object')

    args = parser.parse_args()

    # Upload template to S3
    template_s3_key = f'groundtruth/templates/{args.job_name}/template.html'
    template_s3_uri = upload_template_to_s3(
        args.template_file,
        args.template_s3_bucket,
        template_s3_key
    )

    # Create the labeling job
    response = create_labeling_job(
        job_name=args.job_name,
        input_manifest_s3_uri=args.input_manifest,
        output_s3_uri=args.output_path,
        task_template_s3_uri=template_s3_uri,
        role_arn=args.role_arn,
        workteam_arn=args.workteam_arn,
        pre_lambda_arn=args.pre_lambda_arn,
        post_lambda_arn=args.post_lambda_arn,
        num_workers_per_object=args.workers_per_object
    )

    print("\n" + "=" * 80)
    print("Setup complete! Next steps:")
    print("=" * 80)
    print("1. Workers will receive email invitations to join the labeling workforce")
    print("2. Monitor job progress in the SageMaker console")
    print("3. Results will be saved to:", args.output_path)
    print("4. Annotations will be stored in Aurora PostgreSQL via the post-annotation Lambda")


if __name__ == '__main__':
    main()
