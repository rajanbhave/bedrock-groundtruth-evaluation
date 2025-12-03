"""
Pre-Annotation Lambda Function for SageMaker Ground Truth with Bedrock Knowledge Base Integration
This function uses Amazon Bedrock Knowledge Base with RAG to generate context-aware responses
before presenting them to human workers for evaluation.
"""

import json
import logging
import os
import hashlib
import time
import boto3
from typing import Dict, Optional, Any

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime', region_name='us-east-1')
s3_client = boto3.client('s3')

# Environment variables with defaults
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID')
MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'anthropic.claude-3-sonnet-20240229-v1:0')
MAX_TOKENS = int(os.environ.get('MAX_TOKENS', '2000'))
TEMPERATURE = float(os.environ.get('TEMPERATURE', '0.7'))
TOP_P = float(os.environ.get('TOP_P', '0.9'))
ENABLE_CACHING = os.environ.get('ENABLE_CACHING', 'true').lower() == 'true'
CACHE_BUCKET = os.environ.get('CACHE_BUCKET', '')
CACHE_PREFIX = os.environ.get('CACHE_PREFIX', 'bedrock-cache/')
SYSTEM_PROMPT = os.environ.get('SYSTEM_PROMPT', '')
MAX_RETRIES = int(os.environ.get('MAX_RETRIES', '3'))

# Validate required configuration
if not KNOWLEDGE_BASE_ID:
    raise ValueError("KNOWLEDGE_BASE_ID environment variable is required")


def lambda_handler(event, context):
    """
    Process input data from Ground Truth and invoke Bedrock to generate responses.

    Args:
        event: Contains the taskObject from the input manifest
        context: Lambda context object

    Returns:
        Dictionary with taskInput for the worker UI template
    """

    try:
        logger.info(f"Received event: {json.dumps(event)}")

        # Extract the data object from the event
        data_object = event.get('dataObject', {})

        # Parse the input data from JSONL manifest
        question = data_object.get('question', '')
        reference_response = data_object.get('reference_response', '')
        category = data_object.get('category', 'General')
        prompt_id = data_object.get('prompt_id', 'N/A')

        # Check if response is pre-generated (backward compatibility)
        pre_generated_response = data_object.get('response', '')

        if pre_generated_response:
            # Use pre-generated response if available
            logger.info(f"Using pre-generated response for prompt_id: {prompt_id}")
            response_text = pre_generated_response
        else:
            # Generate response on-the-fly using Bedrock
            logger.info(f"Generating response for prompt_id: {prompt_id} using Bedrock")
            response_text = generate_response(question, category, prompt_id)

        # Prepare the task input for the worker UI template
        task_input = {
            'taskObject': event['dataObject'],  # Required by Ground Truth
            'question': question,
            'response': response_text,
            'reference_response': reference_response,
            'category': category,
            'prompt_id': prompt_id
        }

        logger.info(f"Successfully prepared task input for prompt_id: {prompt_id}")

        return {
            'taskInput': task_input,
            'humanAnnotationRequired': 'true'
        }

    except Exception as e:
        logger.error(f"Error in pre-annotation processing: {str(e)}", exc_info=True)
        return {
            'taskInput': {
                'question': data_object.get('question', 'Error occurred'),
                'response': f'Error generating response: {str(e)}',
                'reference_response': '',
                'category': 'Error',
                'prompt_id': data_object.get('prompt_id', 'error')
            },
            'humanAnnotationRequired': 'true'  # Still allow human to review the error
        }


def generate_response(question: str, category: str = '', prompt_id: str = '') -> str:
    """
    Generate a response using Bedrock with caching and retry logic.

    Args:
        question: The user's question
        category: Category for context
        prompt_id: Unique identifier for the prompt

    Returns:
        Generated response text
    """

    # Check cache first if enabled
    if ENABLE_CACHING and CACHE_BUCKET:
        cached_response = get_cached_response(question)
        if cached_response:
            logger.info(f"Cache hit for prompt_id: {prompt_id}")
            return cached_response

    # Generate new response from Bedrock
    response_text = invoke_bedrock_with_retry(question, category)

    # Cache the response if enabled
    if ENABLE_CACHING and CACHE_BUCKET and response_text:
        cache_response(question, response_text)

    return response_text


def invoke_bedrock_with_retry(question: str, category: str = '', retries: int = 0) -> str:
    """
    Invoke Bedrock Knowledge Base with RAG and retry logic for transient failures.

    Args:
        question: The user's question
        category: Category for additional context
        retries: Current retry attempt

    Returns:
        Model response text with UK pension knowledge context
    """

    try:
        # Prepare system prompt if provided
        system_prompt = SYSTEM_PROMPT or get_default_system_prompt()

        # Add category context if available
        enhanced_question = question
        if category:
            enhanced_question = f"[Category: {category}]\n\n{question}"

        logger.info(f"Querying Knowledge Base {KNOWLEDGE_BASE_ID} with model: {MODEL_ID}")
        start_time = time.time()

        # Use Knowledge Base retrieve_and_generate for RAG
        response = bedrock_agent_runtime.retrieve_and_generate(
            input={
                'text': enhanced_question
            },
            retrieveAndGenerateConfiguration={
                'type': 'KNOWLEDGE_BASE',
                'knowledgeBaseConfiguration': {
                    'knowledgeBaseId': KNOWLEDGE_BASE_ID,
                    'modelArn': f'arn:aws:bedrock:us-east-1::foundation-model/{MODEL_ID}',
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

        elapsed_time = time.time() - start_time
        logger.info(f"Knowledge Base retrieval completed in {elapsed_time:.2f} seconds")

        # Extract the generated text from Knowledge Base response
        ai_response = response.get('output', {}).get('text', '')

        if not ai_response:
            logger.warning("No response text in Knowledge Base output")
            return "Error: Knowledge Base returned empty response"

        # Log citations/sources if available
        citations = response.get('citations', [])
        if citations:
            logger.info(f"Response generated with {len(citations)} citation(s) from Knowledge Base")

        return ai_response.strip()

    except bedrock_agent_runtime.exceptions.ThrottlingException as e:
        # Rate limiting - retry with exponential backoff
        if retries < MAX_RETRIES:
            backoff_time = (2 ** retries) * 1
            logger.warning(f"Throttled by Bedrock. Retrying in {backoff_time}s (attempt {retries + 1}/{MAX_RETRIES})")
            time.sleep(backoff_time)
            return invoke_bedrock_with_retry(question, category, retries + 1)
        else:
            logger.error(f"Max retries exceeded due to throttling")
            return f"Error: Service temporarily unavailable (throttled). Please try again later."

    except Exception as e:
        # General error handling
        if retries < MAX_RETRIES:
            logger.warning(f"Error during Knowledge Base query: {str(e)}. Retrying (attempt {retries + 1}/{MAX_RETRIES})")
            time.sleep(2)
            return invoke_bedrock_with_retry(question, category, retries + 1)
        else:
            logger.error(f"Max retries exceeded. Error: {str(e)}", exc_info=True)
            return f"Error: Failed to generate response from Knowledge Base after {MAX_RETRIES} attempts."


def get_cached_response(question: str) -> Optional[str]:
    """
    Retrieve cached response from S3 if available.

    Args:
        question: The user's question

    Returns:
        Cached response text or None if not found
    """

    try:
        cache_key = get_cache_key(question)
        s3_key = f"{CACHE_PREFIX}{cache_key}.json"

        logger.debug(f"Checking cache at s3://{CACHE_BUCKET}/{s3_key}")

        response = s3_client.get_object(Bucket=CACHE_BUCKET, Key=s3_key)
        cache_data = json.loads(response['Body'].read().decode('utf-8'))

        # Check if cache is still valid (7 days TTL)
        cache_age = time.time() - cache_data.get('timestamp', 0)
        if cache_age < (7 * 24 * 60 * 60):  # 7 days
            return cache_data.get('response')
        else:
            logger.info(f"Cache expired for key: {cache_key}")
            return None

    except s3_client.exceptions.NoSuchKey:
        logger.debug(f"Cache miss for question")
        return None
    except Exception as e:
        logger.warning(f"Error reading from cache: {str(e)}")
        return None


def cache_response(question: str, response: str) -> None:
    """
    Cache the generated response in S3.

    Args:
        question: The user's question
        response: The generated response
    """

    try:
        cache_key = get_cache_key(question)
        s3_key = f"{CACHE_PREFIX}{cache_key}.json"

        cache_data = {
            'question': question,
            'response': response,
            'model_id': MODEL_ID,
            'timestamp': time.time()
        }

        s3_client.put_object(
            Bucket=CACHE_BUCKET,
            Key=s3_key,
            Body=json.dumps(cache_data),
            ContentType='application/json'
        )

        logger.debug(f"Cached response at s3://{CACHE_BUCKET}/{s3_key}")

    except Exception as e:
        logger.warning(f"Error caching response: {str(e)}")


def get_cache_key(question: str) -> str:
    """
    Generate a cache key based on question and model configuration.

    Args:
        question: The user's question

    Returns:
        SHA256 hash as cache key
    """

    cache_input = f"{question}|{MODEL_ID}|{TEMPERATURE}|{MAX_TOKENS}"
    return hashlib.sha256(cache_input.encode()).hexdigest()


def get_default_system_prompt() -> str:
    """
    Get the default system prompt for the retirement planning coach.

    Returns:
        System prompt text
    """

    return """You are a helpful retirement planning assistant. Your role is to provide general educational information about retirement planning topics.

IMPORTANT GUIDELINES:
- Do NOT provide personalized financial advice, specific investment recommendations, or tax advice
- Always suggest consulting with a certified financial planner or advisor for personalized guidance
- Explain general concepts, frameworks, and considerations
- Be clear about your limitations
- Maintain a conversational yet professional tone
- Ensure accuracy and provide disclaimers where appropriate

Focus on being educational, helpful, and compliant with financial advisory regulations."""


def get_model_specific_body(question: str, model_id: str) -> Dict[str, Any]:
    """
    Get model-specific request body format.
    Currently supports Claude models; can be extended for other models.

    Args:
        question: The user's question
        model_id: Bedrock model identifier

    Returns:
        Request body dictionary
    """

    if 'claude' in model_id.lower() or 'anthropic' in model_id.lower():
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": question}],
            "temperature": TEMPERATURE,
            "top_p": TOP_P
        }
    elif 'titan' in model_id.lower():
        return {
            "inputText": question,
            "textGenerationConfig": {
                "maxTokenCount": MAX_TOKENS,
                "temperature": TEMPERATURE,
                "topP": TOP_P
            }
        }
    else:
        # Default format (Claude-style)
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": MAX_TOKENS,
            "messages": [{"role": "user", "content": question}],
            "temperature": TEMPERATURE
        }
