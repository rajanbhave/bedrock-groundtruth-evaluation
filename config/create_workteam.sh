#!/bin/bash

# Script to create a SageMaker Ground Truth private workteam
# This script creates the necessary Cognito resources and workteam

set -e

echo "========================================"
echo "SageMaker Ground Truth Workteam Setup"
echo "========================================"
echo ""

# Configuration
WORKTEAM_NAME="retirement-coach-evaluators"
REGION="us-east-1"

# Prompt for worker emails
echo "Enter worker email addresses (comma-separated):"
echo "Example: user1@example.com,user2@example.com"
read -r WORKER_EMAILS

# Convert comma-separated emails to array
IFS=',' read -ra EMAIL_ARRAY <<< "$WORKER_EMAILS"

echo ""
echo "Creating workteam with ${#EMAIL_ARRAY[@]} workers..."
echo ""

# Check if Cognito user pool already exists for SageMaker Ground Truth
echo "Step 1: Checking for existing Cognito user pool..."

# Try to find existing SageMaker workforce
EXISTING_WORKFORCE=$(aws sagemaker list-workteams --region $REGION --query "Workteams[?WorkteamName=='$WORKTEAM_NAME'].WorkteamArn" --output text 2>/dev/null || echo "")

if [ -n "$EXISTING_WORKFORCE" ]; then
    echo "✓ Workteam already exists: $EXISTING_WORKFORCE"
    echo ""
    echo "To add workers to existing workteam, use:"
    echo "aws sagemaker describe-workteam --workteam-name $WORKTEAM_NAME"
    exit 0
fi

# Create Cognito User Pool
echo "Step 2: Creating Cognito User Pool for SageMaker workforce..."

USER_POOL_ID=$(aws cognito-idp create-user-pool \
    --pool-name "sagemaker-groundtruth-${WORKTEAM_NAME}" \
    --policies "PasswordPolicy={MinimumLength=8,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}" \
    --auto-verified-attributes email \
    --username-attributes email \
    --region $REGION \
    --query 'UserPool.Id' \
    --output text 2>&1)

if [ $? -ne 0 ]; then
    echo "Error creating user pool. It might already exist."
    echo "Try using the SageMaker console to create the workteam instead."
    exit 1
fi

echo "✓ Created User Pool: $USER_POOL_ID"

# Create User Pool Client
echo "Step 3: Creating User Pool Client..."

CLIENT_ID=$(aws cognito-idp create-user-pool-client \
    --user-pool-id $USER_POOL_ID \
    --client-name "sagemaker-client" \
    --region $REGION \
    --query 'UserPoolClient.ClientId' \
    --output text)

echo "✓ Created Client: $CLIENT_ID"

# Create User Group
echo "Step 4: Creating 'evaluators' user group..."

aws cognito-idp create-group \
    --user-pool-id $USER_POOL_ID \
    --group-name evaluators \
    --description "Retirement coach evaluators" \
    --region $REGION >/dev/null

echo "✓ Created user group: evaluators"

# Add users to Cognito
echo "Step 5: Adding users to Cognito User Pool..."

for email in "${EMAIL_ARRAY[@]}"; do
    # Trim whitespace
    email=$(echo "$email" | xargs)

    echo "  Adding: $email"

    aws cognito-idp admin-create-user \
        --user-pool-id $USER_POOL_ID \
        --username "$email" \
        --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
        --desired-delivery-mediums EMAIL \
        --region $REGION >/dev/null 2>&1 || echo "    (User may already exist)"

    # Add user to group
    aws cognito-idp admin-add-user-to-group \
        --user-pool-id $USER_POOL_ID \
        --username "$email" \
        --group-name evaluators \
        --region $REGION >/dev/null 2>&1
done

echo "✓ Added ${#EMAIL_ARRAY[@]} users"

# Create workteam JSON
echo "Step 6: Creating workteam..."

WORKTEAM_JSON=$(cat <<EOF
{
  "WorkteamName": "$WORKTEAM_NAME",
  "MemberDefinitions": [
    {
      "CognitoMemberDefinition": {
        "UserPool": "$USER_POOL_ID",
        "UserGroup": "evaluators",
        "ClientId": "$CLIENT_ID"
      }
    }
  ],
  "Description": "Private workforce for evaluating retirement planning model responses"
}
EOF
)

# Create workteam
WORKTEAM_ARN=$(aws sagemaker create-workteam \
    --cli-input-json "$WORKTEAM_JSON" \
    --region $REGION \
    --query 'WorkteamArn' \
    --output text 2>&1)

if [ $? -eq 0 ]; then
    echo "✓ Workteam created successfully!"
    echo ""
    echo "========================================"
    echo "Setup Complete!"
    echo "========================================"
    echo ""
    echo "Workteam ARN: $WORKTEAM_ARN"
    echo "User Pool ID: $USER_POOL_ID"
    echo "Client ID: $CLIENT_ID"
    echo ""
    echo "Workers will receive email invitations at:"
    for email in "${EMAIL_ARRAY[@]}"; do
        echo "  - $(echo "$email" | xargs)"
    done
    echo ""
    echo "Next steps:"
    echo "1. Workers should check their email for temporary passwords"
    echo "2. Use this ARN when creating Ground Truth labeling jobs"
    echo "3. Save the ARN for reference:"
    echo "   export WORKTEAM_ARN='$WORKTEAM_ARN'"
else
    echo "Error creating workteam: $WORKTEAM_ARN"
    exit 1
fi
