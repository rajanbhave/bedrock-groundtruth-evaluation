"""
Bedrock API Lambda - Exposes Bedrock Knowledge Base via API Gateway for dynamic question evaluation.

This Lambda is called by the Ground Truth HTML template via JavaScript (AJAX) to generate
AI responses on-demand based on worker-provided questions using RAG with Knowledge Base.

Architecture:
  Worker types question → JavaScript calls API Gateway → This Lambda →
  Knowledge Base retrieval → Bedrock with context → Response

Environment Variables:
  - KNOWLEDGE_BASE_ID: Bedrock Knowledge Base ID (required)
  - BEDROCK_MODEL_ID: Model to use (default: claude-3-sonnet)
  - S3_CACHE_BUCKET: Optional S3 bucket for response caching
  - S3_CACHE_PREFIX: Optional S3 prefix for cache (default: bedrock-cache/)
"""

import json
import boto3
import hashlib
import os
import logging
from datetime import datetime
from typing import Dict, Optional

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
s3_client = boto3.client('s3')

# Configuration (must be set via Lambda environment variables)
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID')
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')
S3_CACHE_BUCKET = os.environ.get('S3_CACHE_BUCKET', '')
S3_CACHE_PREFIX = os.environ.get('S3_CACHE_PREFIX', 'bedrock-cache/')
MAX_TOKENS = int(os.environ.get('MAX_TOKENS', '2000'))
TEMPERATURE = float(os.environ.get('TEMPERATURE', '0.7'))

# Validate required configuration
if not KNOWLEDGE_BASE_ID:
    raise ValueError("KNOWLEDGE_BASE_ID environment variable is required")


def lambda_handler(event, context):
    """
    API Gateway Lambda handler for Bedrock invocation.

    Expected event body:
    {
        "question": "User's question about retirement planning",
        "model_id": "anthropic.claude-3-sonnet-20240229-v1:0" (optional),
        "use_cache": true (optional, default: true)
    }

    Returns:
    {
        "statusCode": 200,
        "body": {
            "response": "AI-generated response",
            "question": "Original question",
            "model_id": "Model used",
            "cached": false,
            "timestamp": "2025-12-01T12:00:00Z"
        }
    }
    """
    try:
        # Parse request body
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})

        # Extract parameters
        question = body.get('question', '').strip()
        model_id = body.get('model_id', BEDROCK_MODEL_ID)
        use_cache = body.get('use_cache', True)

        # Validate question
        if not question:
            return create_response(400, {'error': 'Question is required'})

        if len(question) < 10:
            return create_response(400, {'error': 'Question must be at least 10 characters'})

        if len(question) > 2000:
            return create_response(400, {'error': 'Question must be less than 2000 characters'})

        logger.info(f"Processing question: {question[:100]}...")

        # Check cache if enabled
        cached_response = None
        if use_cache and S3_CACHE_BUCKET:
            cached_response = get_cached_response(question, model_id)

        if cached_response:
            logger.info("Using cached response")
            return create_response(200, {
                'response': cached_response,
                'question': question,
                'model_id': model_id,
                'cached': True,
                'timestamp': datetime.utcnow().isoformat() + 'Z'
            })

        # Generate new response from Bedrock
        logger.info(f"Invoking Bedrock model: {model_id}")
        ai_response = invoke_bedrock_model(question, model_id)

        # Cache the response
        if use_cache and S3_CACHE_BUCKET:
            cache_response(question, model_id, ai_response)

        # Return response
        return create_response(200, {
            'response': ai_response,
            'question': question,
            'model_id': model_id,
            'cached': False,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        })

    except Exception as e:
        logger.error(f"Error processing request: {str(e)}", exc_info=True)
        return create_response(500, {
            'error': 'Internal server error',
            'message': str(e)
        })


def invoke_bedrock_model(question: str, model_id: str) -> str:
    """
    Invoke Bedrock Knowledge Base with RAG to generate response.

    Args:
        question: User's question
        model_id: Bedrock model ID

    Returns:
        AI-generated response text with UK pension knowledge context
    """
    # System prompt for UK retirement planning with retrieved context
    system_prompt = """You are an expert UK retirement planning advisor. Use the provided context from official UK pension documentation to answer questions accurately.

Guidelines:
- Base your answer on the retrieved pension documentation
- Always include appropriate disclaimers for financial advice
- Be clear about general guidance vs. personalized advice
- Mention when professional financial advice should be sought
- Use UK-specific terminology and regulations
- Be concise but comprehensive
- If the context doesn't contain enough information, acknowledge this"""

    try:
        # Use Knowledge Base retrieve_and_generate for RAG
        logger.info(f"Querying Knowledge Base: {KNOWLEDGE_BASE_ID}")
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': question
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                    'modelArn': f'arn:aws:bedrock:us-east-1::foundation-model/{model_id}',
                    'generationConfiguration': {
                        'promptTemplate': {
                            'textPromptTemplate': f'{system_prompt}\n\nContext: $search_results$\n\nQuestion: $query$\n\nAnswer:'
                        },
                        'inferenceConfig': {
                            'textInferenceConfig': {
                                'maxTokens': MAX_TOKENS,
                                'temperature': TEMPERATURE
                            }
                        }
                    }
                }
            }
        )

        # Extract the generated text from Knowledge Base response
        ai_response = response.get('output', {}).get('text', '')

        if not ai_response:
            logger.warning("No response text in Knowledge Base output")
            raise Exception("Knowledge Base returned empty response")

        # Log citations/sources if available
        citations = response.get('citations', [])
        if citations:
            logger.info(f"Response generated with {len(citations)} citation(s) from Knowledge Base")
            for idx, citation in enumerate(citations[:3]):  # Log first 3 citations
                retrieved_refs = citation.get('retrievedReferences', [])
                if retrieved_refs:
                    source_uri = retrieved_refs[0].get('location', {}).get('s3Location', {}).get('uri', 'Unknown')
                    logger.info(f"Citation {idx+1}: {source_uri}")

        logger.info(f"Generated response length: {len(ai_response)} characters")
        return ai_response.strip()

    except Exception as e:
        logger.error(f"Knowledge Base retrieval failed: {str(e)}", exc_info=True)
        raise Exception(f"Failed to generate AI response from Knowledge Base: {str(e)}")


def get_cached_response(question: str, model_id: str) -> Optional[str]:
    """
    Retrieve cached response from S3 if available.

    Args:
        question: User's question
        model_id: Model ID used

    Returns:
        Cached response or None if not found
    """
    if not S3_CACHE_BUCKET:
        return None

    try:
        cache_key = generate_cache_key(question, model_id)
        s3_key = f"{S3_CACHE_PREFIX}{cache_key}.json"

        logger.info(f"Checking cache: s3://{S3_CACHE_BUCKET}/{s3_key}")

        response = s3_client.get_object(
            Bucket=S3_CACHE_BUCKET,
            Key=s3_key
        )

        cache_data = json.loads(response['Body'].read().decode('utf-8'))
        logger.info("Cache hit!")
        return cache_data.get('response')

    except s3_client.exceptions.NoSuchKey:
        logger.info("Cache miss")
        return None
    except Exception as e:
        logger.warning(f"Error reading cache: {str(e)}")
        return None


def cache_response(question: str, model_id: str, response: str) -> None:
    """
    Cache response to S3 for future use.

    Args:
        question: User's question
        model_id: Model ID used
        response: AI-generated response
    """
    if not S3_CACHE_BUCKET:
        return

    try:
        cache_key = generate_cache_key(question, model_id)
        s3_key = f"{S3_CACHE_PREFIX}{cache_key}.json"

        cache_data = {
            'question': question,
            'response': response,
            'model_id': model_id,
            'timestamp': datetime.utcnow().isoformat() + 'Z'
        }

        s3_client.put_object(
            Bucket=S3_CACHE_BUCKET,
            Key=s3_key,
            Body=json.dumps(cache_data),
            ContentType='application/json'
        )

        logger.info(f"Cached response: s3://{S3_CACHE_BUCKET}/{s3_key}")

    except Exception as e:
        logger.warning(f"Error caching response: {str(e)}")


def generate_cache_key(question: str, model_id: str) -> str:
    """
    Generate cache key from question and model ID.

    Args:
        question: User's question
        model_id: Model ID

    Returns:
        SHA256 hash of normalized question + model
    """
    normalized = f"{question.lower().strip()}|{model_id}"
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def create_response(status_code: int, body: Dict) -> Dict:
    """
    Create API Gateway response with CORS headers.

    Args:
        status_code: HTTP status code
        body: Response body dictionary

    Returns:
        API Gateway response format
    """
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
            'Access-Control-Allow-Methods': 'POST,OPTIONS'
        },
        'body': json.dumps(body)
    }
