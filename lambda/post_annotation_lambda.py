"""
Post-Annotation Lambda Function for SageMaker Ground Truth
This function processes human annotations and stores them in Aurora PostgreSQL.
Simplified version matching the single rating + feedback template.
"""

import json
import logging
import os
import boto3
from datetime import datetime
from typing import Dict, List, Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
s3_client = boto3.client('s3')
secretsmanager_client = boto3.client('secretsmanager')


def lambda_handler(event, context):
    """
    Process annotations from human workers and store in Aurora PostgreSQL.

    Args:
        event: Contains consolidated annotations from Ground Truth
        context: Lambda context object

    Returns:
        Dictionary with consolidation result for Ground Truth output manifest
    """

    try:
        logger.info(f"Received post-annotation event: {json.dumps(event)}")

        # Extract annotation data from S3
        annotations_data = []

        if 'payload' in event and 's3Uri' in event['payload']:
            s3_uri = event['payload']['s3Uri']
            logger.info(f"Downloading annotations from: {s3_uri}")
            annotations_data = download_from_s3(s3_uri)
        else:
            logger.error("No S3 URI found in event payload")
            return create_error_response("No annotations found")

        # Process the consolidation request
        if isinstance(annotations_data, list):
            for item in annotations_data:
                process_annotation_item(item, event)
        else:
            process_annotation_item(annotations_data, event)

        # Return success response
        return [{
            "datasetObjectId": item.get("datasetObjectId"),
            "consolidatedAnnotation": {
                "content": {
                    event.get("labelAttributeName", "evaluation-result"): {
                        "processed": True
                    }
                }
            }
        } for item in (annotations_data if isinstance(annotations_data, list) else [annotations_data])]

    except Exception as e:
        logger.error(f"Error in post-annotation processing: {str(e)}", exc_info=True)
        return create_error_response(str(e))


def process_annotation_item(item: Dict, event: Dict) -> None:
    """Process a single annotation item and store in Aurora."""

    try:
        # Extract worker annotations
        annotations = item.get("annotations", [])

        if not annotations:
            logger.warning(f"No annotations found")
            return

        # Process first annotation (we're using 1 worker per object)
        annotation = annotations[0]
        answer_content = annotation.get("annotationData", {}).get("content", "{}")

        # Parse JSON string to dict
        if isinstance(answer_content, str):
            answer = json.loads(answer_content)
        else:
            answer = answer_content

        # Extract all fields from answer (they're included in the form submission)
        prompt_id = answer.get("prompt_id", "unknown")
        question = answer.get("question", "")
        response = answer.get("response", "")
        category = answer.get("category", "General")

        # Extract rating (handle different formats)
        overall_rating = extract_rating(answer.get("overall_rating", {}))
        feedback = answer.get("feedback", "")

        # Worker metadata
        worker_id = annotation.get("workerId", "unknown")
        time_spent = annotation.get("timeSpentInSeconds", 0)
        acceptance_time = annotation.get("acceptanceTime", "")
        submission_time = annotation.get("submissionTime", "")

        # Labeling job metadata
        labeling_job_arn = event.get("labelingJobArn", "")

        # Store in Aurora
        evaluation_data = {
            "prompt_id": prompt_id,
            "question": question,
            "response": response,
            "category": category,
            "overall_rating": overall_rating,
            "feedback": feedback if feedback else None,
            "worker_id": worker_id,
            "time_spent_seconds": time_spent,
            "acceptance_time": acceptance_time if acceptance_time else None,
            "submission_time": submission_time if submission_time else None,
            "labeling_job_arn": labeling_job_arn,
            "metadata": json.dumps({"raw_answer": answer})
        }

        store_in_aurora(evaluation_data)
        logger.info(f"Successfully processed and stored evaluation for prompt_id: {prompt_id}")

    except Exception as e:
        logger.error(f"Error processing annotation item: {str(e)}", exc_info=True)
        raise


def extract_rating(rating_obj: Dict) -> int:
    """
    Extract rating value from the rating object.

    Args:
        rating_obj: Dict like {"1": false, "2": false, "3": false, "4": true, "5": false}

    Returns:
        Integer rating value (1-5)
    """
    if isinstance(rating_obj, dict):
        for key, value in rating_obj.items():
            if value is True:
                return int(key)
    elif isinstance(rating_obj, (int, str)):
        return int(rating_obj)

    return 3  # Default to 3 if unable to parse


def store_in_aurora(evaluation_data: Dict) -> None:
    """
    Store evaluation data in Aurora PostgreSQL.

    Args:
        evaluation_data: Dictionary with evaluation data
    """

    try:
        # Get database credentials from Secrets Manager
        db_credentials = get_db_credentials()

        # Import psycopg2 (must be included in Lambda layer)
        import psycopg2
        from psycopg2.extras import Json

        # Connect to Aurora PostgreSQL with SSL
        conn = psycopg2.connect(
            host=db_credentials['host'],
            port=db_credentials['port'],
            database=db_credentials['dbname'],
            user=db_credentials['username'],
            password=db_credentials['password'],
            sslmode='require'
        )

        cursor = conn.cursor()

        # Insert evaluation record
        insert_query = """
        INSERT INTO evaluations (
            prompt_id, question, response, category,
            overall_rating, feedback,
            worker_id, time_spent_seconds,
            acceptance_time, submission_time,
            labeling_job_arn, metadata
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        ON CONFLICT (prompt_id) DO UPDATE SET
            overall_rating = EXCLUDED.overall_rating,
            feedback = EXCLUDED.feedback,
            worker_id = EXCLUDED.worker_id,
            time_spent_seconds = EXCLUDED.time_spent_seconds,
            acceptance_time = EXCLUDED.acceptance_time,
            submission_time = EXCLUDED.submission_time,
            labeling_job_arn = EXCLUDED.labeling_job_arn,
            metadata = EXCLUDED.metadata
        """

        cursor.execute(insert_query, (
            evaluation_data['prompt_id'],
            evaluation_data['question'],
            evaluation_data['response'],
            evaluation_data['category'],
            evaluation_data['overall_rating'],
            evaluation_data['feedback'],
            evaluation_data['worker_id'],
            evaluation_data['time_spent_seconds'],
            evaluation_data['acceptance_time'],
            evaluation_data['submission_time'],
            evaluation_data['labeling_job_arn'],
            evaluation_data['metadata']
        ))

        conn.commit()
        cursor.close()
        conn.close()

        logger.info(f"Successfully stored evaluation data for prompt_id: {evaluation_data['prompt_id']}")

    except Exception as e:
        logger.error(f"Error storing data in Aurora: {str(e)}", exc_info=True)
        raise


def get_db_credentials() -> Dict:
    """
    Retrieve database credentials from AWS Secrets Manager.

    Returns:
        Dictionary with database connection parameters
    """

    secret_name = os.environ.get('DB_SECRET_NAME', 'aurora-postgres-credentials-latest')

    try:
        response = secretsmanager_client.get_secret_value(SecretId=secret_name)
        secret = json.loads(response['SecretString'])

        return {
            'host': secret['host'],
            'port': secret.get('port', 5432),
            'dbname': secret['dbname'],
            'username': secret['username'],
            'password': secret['password']
        }

    except Exception as e:
        logger.error(f"Error retrieving database credentials: {str(e)}")
        raise


def download_from_s3(s3_uri: str) -> Any:
    """
    Download data from S3.

    Args:
        s3_uri: S3 URI (s3://bucket/key)

    Returns:
        Downloaded data (parsed JSON if applicable)
    """

    # Parse S3 URI
    parts = s3_uri.replace('s3://', '').split('/', 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ''

    try:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        content = response['Body'].read().decode('utf-8')

        # Try to parse as JSON
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return content

    except Exception as e:
        logger.error(f"Error downloading from S3: {str(e)}")
        raise


def create_error_response(error_message: str) -> Dict:
    """Create an error response for Ground Truth."""
    return {
        "consolidatedAnnotation": {
            "content": {
                "error": error_message
            }
        }
    }
