"""
Batch Response Generation Script
Generates responses from Bedrock for all questions in a dataset and saves them
to a new JSONL file. Useful for:
1. Pre-generating responses for cost optimization
2. Testing different models/prompts
3. Creating cached responses for faster Ground Truth jobs
"""

import boto3
import json
import argparse
import time
from datetime import datetime
from typing import List, Dict
import sys


def load_config(config_file='bedrock_config.json'):
    """Load configuration from JSON file."""

    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Warning: Config file '{config_file}' not found. Using defaults.")
        return {
            'model_id': 'anthropic.claude-3-sonnet-20240229-v1:0',
            'system_prompt': '',
            'inference_params': {
                'max_tokens': 1000,
                'temperature': 0.7,
                'top_p': 0.9
            }
        }


def load_dataset(input_file):
    """Load questions from JSONL file."""

    questions = []
    with open(input_file, 'r') as f:
        for line in f:
            if line.strip():
                questions.append(json.loads(line))

    return questions


def generate_response(bedrock_client, question, category, config):
    """Generate a single response using Bedrock."""

    model_id = config['model_id']
    system_prompt = config.get('system_prompt', '')
    params = config['inference_params']

    # Add category context
    enhanced_question = question
    if category:
        enhanced_question = f"[Category: {category}]\n\n{question}"

    # Prepare request
    request_body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": params['max_tokens'],
        "messages": [
            {
                "role": "user",
                "content": enhanced_question
            }
        ],
        "temperature": params['temperature'],
        "top_p": params.get('top_p', 0.9)
    }

    if system_prompt:
        request_body["system"] = system_prompt

    try:
        response = bedrock_client.invoke_model(
            modelId=model_id,
            body=json.dumps(request_body)
        )

        response_body = json.loads(response['body'].read())
        return response_body['content'][0]['text']

    except Exception as e:
        print(f"  Error: {str(e)}")
        return f"Error generating response: {str(e)}"


def batch_generate(input_file, output_file, config_file='bedrock_config.json', delay=0.5):
    """
    Generate responses for all questions in the input file.

    Args:
        input_file: Path to input JSONL file with questions
        output_file: Path to output JSONL file with responses
        config_file: Path to Bedrock configuration file
        delay: Delay between requests (seconds) to avoid throttling
    """

    print("=" * 80)
    print("BATCH RESPONSE GENERATION")
    print("=" * 80)
    print(f"Input file:  {input_file}")
    print(f"Output file: {output_file}")
    print(f"Config file: {config_file}")
    print("")

    # Load configuration
    config = load_config(config_file)
    print(f"Model: {config['model_id']}")
    print(f"Max tokens: {config['inference_params']['max_tokens']}")
    print(f"Temperature: {config['inference_params']['temperature']}")
    print("")

    # Load questions
    print("Loading questions...")
    dataset = load_dataset(input_file)
    total = len(dataset)
    print(f"Found {total} questions\n")

    # Initialize Bedrock client
    bedrock_runtime = boto3.client('bedrock-runtime')

    # Generate responses
    results = []
    start_time = time.time()
    successful = 0
    failed = 0

    print("Generating responses...")
    print("-" * 80)

    for i, item in enumerate(dataset, 1):
        prompt_id = item.get('prompt_id', f'prompt_{i}')
        question = item.get('question', '')
        category = item.get('category', 'General')

        print(f"[{i}/{total}] {prompt_id}: {question[:60]}...")

        try:
            response_text = generate_response(
                bedrock_runtime,
                question,
                category,
                config
            )

            # Add response to item
            item['response'] = response_text
            results.append(item)

            successful += 1
            print(f"  ✓ Generated ({len(response_text)} chars)")

        except Exception as e:
            print(f"  ✗ Failed: {str(e)}")
            item['response'] = f"Error: {str(e)}"
            results.append(item)
            failed += 1

        # Delay to avoid throttling
        if i < total and delay > 0:
            time.sleep(delay)

    elapsed_time = time.time() - start_time

    # Save results
    print("\n" + "-" * 80)
    print("Saving results...")

    with open(output_file, 'w') as f:
        for item in results:
            f.write(json.dumps(item) + '\n')

    print(f"✓ Saved to: {output_file}")

    # Summary
    print("\n" + "=" * 80)
    print("GENERATION COMPLETE")
    print("=" * 80)
    print(f"Total questions: {total}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Total time: {elapsed_time:.2f} seconds")
    print(f"Average time per request: {elapsed_time / total:.2f} seconds")
    print("")

    # Cost estimation
    estimate_cost(total, config)


def estimate_cost(num_requests, config):
    """Estimate the cost of the batch generation."""

    model_id = config['model_id']

    # Token estimates
    avg_input_tokens = 150
    avg_output_tokens = config['inference_params']['max_tokens'] * 0.8  # Assume 80% of max

    # Pricing (per 1M tokens)
    pricing = {
        'claude-3-haiku': {'input': 0.25, 'output': 1.25},
        'claude-3-sonnet': {'input': 3.0, 'output': 15.0},
        'claude-3-opus': {'input': 15.0, 'output': 75.0}
    }

    # Determine model pricing
    if 'haiku' in model_id.lower():
        prices = pricing['claude-3-haiku']
        model_name = 'Claude 3 Haiku'
    elif 'sonnet' in model_id.lower():
        prices = pricing['claude-3-sonnet']
        model_name = 'Claude 3 Sonnet'
    elif 'opus' in model_id.lower():
        prices = pricing['claude-3-opus']
        model_name = 'Claude 3 Opus'
    else:
        print("Unknown model for cost estimation")
        return

    input_cost = (avg_input_tokens * num_requests / 1_000_000) * prices['input']
    output_cost = (avg_output_tokens * num_requests / 1_000_000) * prices['output']
    total_cost = input_cost + output_cost

    print(f"Estimated Cost ({model_name}):")
    print(f"  Input tokens:  ~{avg_input_tokens * num_requests:,} (${input_cost:.4f})")
    print(f"  Output tokens: ~{int(avg_output_tokens * num_requests):,} (${output_cost:.4f})")
    print(f"  Total: ${total_cost:.4f}")
    print("")


def compare_models(input_file, output_prefix='comparison'):
    """Generate responses using multiple models for comparison."""

    print("=" * 80)
    print("MULTI-MODEL COMPARISON")
    print("=" * 80)
    print("")

    models = [
        'anthropic.claude-3-haiku-20240307-v1:0',
        'anthropic.claude-3-sonnet-20240229-v1:0',
        'anthropic.claude-3-opus-20240229-v1:0'
    ]

    dataset = load_dataset(input_file)
    print(f"Generating responses for {len(dataset)} questions using {len(models)} models")
    print("")

    for model_id in models:
        model_name = model_id.split('/')[-1].replace('-', '_')
        output_file = f"{output_prefix}_{model_name}.jsonl"

        print(f"\nGenerating with {model_id}...")

        config = {
            'model_id': model_id,
            'system_prompt': '',
            'inference_params': {
                'max_tokens': 1000,
                'temperature': 0.7,
                'top_p': 0.9
            }
        }

        # Save temporary config
        temp_config = f"temp_config_{model_name}.json"
        with open(temp_config, 'w') as f:
            json.dump(config, f)

        # Generate
        batch_generate(input_file, output_file, temp_config, delay=1.0)

        # Cleanup
        import os
        os.remove(temp_config)

    print("\n" + "=" * 80)
    print("All models complete!")
    print("You can now use these datasets to evaluate different models in Ground Truth")


def main():
    parser = argparse.ArgumentParser(
        description='Batch generate Bedrock responses for Ground Truth evaluation'
    )

    parser.add_argument('input_file', help='Input JSONL file with questions')
    parser.add_argument('-o', '--output', help='Output JSONL file with responses',
                        default=None)
    parser.add_argument('-c', '--config', default='bedrock_config.json',
                        help='Configuration file')
    parser.add_argument('-d', '--delay', type=float, default=0.5,
                        help='Delay between requests (seconds)')
    parser.add_argument('--compare-models', action='store_true',
                        help='Generate responses using all Claude 3 models for comparison')

    args = parser.parse_args()

    # Default output filename
    if args.output is None:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        args.output = args.input_file.replace('.jsonl', f'_with_responses_{timestamp}.jsonl')

    try:
        if args.compare_models:
            output_prefix = args.input_file.replace('.jsonl', '')
            compare_models(args.input_file, output_prefix)
        else:
            batch_generate(args.input_file, args.output, args.config, args.delay)

    except KeyboardInterrupt:
        print("\n\nInterrupted by user. Partial results may be saved.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError: {str(e)}")
        sys.exit(1)


if __name__ == '__main__':
    main()
