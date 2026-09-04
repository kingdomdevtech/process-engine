# AWS OIDC Setup for GitHub Actions

This guide walks through configuring GitHub-to-AWS OIDC (OpenID Connect) authentication for the Process Engine Windows deployment workflow.

## Overview

OIDC allows GitHub Actions to authenticate with AWS without storing long-lived access keys. GitHub provides a temporary credential that AWS trusts.

## Prerequisites

- AWS account with IAM permissions to create roles and identity providers
- GitHub repository with admin access (to configure environments and secrets)
- AWS CLI (optional, but helpful for verification)

## Step 1: Create GitHub OIDC Identity Provider in AWS IAM

### Via AWS Console:

1. Go to **IAM** → **Identity providers**
2. Click **Add provider**
3. Select **OpenID Connect**
4. Fill in the following:
   - **Provider URL**: `https://token.actions.githubusercontent.com`
   - **Audience**: `sts.amazonaws.com`
5. Click **Add provider**

### Via AWS CLI:

```bash
aws iam create-open-id-connect-provider \
  --url "https://token.actions.githubusercontent.com" \
  --client-id-list "sts.amazonaws.com" \
  --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea1"
```

The thumbprint is GitHub's static certificate thumbprint (as of Sept 2024; verify at [GitHub Docs](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)).

## Step 2: Create IAM Role for GitHub Actions

### Via AWS Console:

1. Go to **IAM** → **Roles** → **Create role**
2. Select **Custom trust policy**
3. Paste the trust policy below (customize the repository reference)
4. Click **Next**
5. Add the permissions policy (see Step 3)
6. Name the role: `github-process-engine-deploy-role`
7. Click **Create role**

### Trust Policy (Edit as needed):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Federated": "arn:aws:iam::AWS_ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
      },
      "Action": "sts:AssumeRoleWithWebIdentity",
      "Condition": {
        "StringLike": {
          "token.actions.githubusercontent.com:sub": "repo:kingdomdevtech/process-engine:*"
        }
      }
    }
  ]
}
```

**Replace `AWS_ACCOUNT_ID`** with your 12-digit AWS account ID.

**Optional: Restrict to specific branches/environments:**
```json
"token.actions.githubusercontent.com:sub": "repo:kingdomdevtech/process-engine:ref:refs/heads/main"
```

## Step 3: Create Permissions Policy

### Via AWS Console:

1. In the role creation flow (Step 2, after "Next"), click **Create policy**
2. Select **JSON** tab
3. Paste the policy below
4. Name it: `github-process-engine-deploy-policy`
5. Create and attach it to the role

### Permissions Policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:PutObjectAcl"
      ],
      "Resource": "arn:aws:s3:::S3_BUCKET_NAME/process-engine/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "ssm:SendCommand",
        "ssm:GetCommandInvocation"
      ],
      "Resource": [
        "arn:aws:ec2:AWS_REGION:AWS_ACCOUNT_ID:instance/i-*",
        "arn:aws:ssm:AWS_REGION::document/AWS-RunPowerShellScript"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "ec2messages:AcknowledgeMessage",
        "ec2messages:DeleteMessage",
        "ec2messages:FailMessage",
        "ec2messages:GetEndpoint",
        "ec2messages:GetMessages",
        "ec2messages:SendReply",
        "ssmmessages:CreateControlChannel",
        "ssmmessages:CreateDataChannel",
        "ssmmessages:OpenControlChannel",
        "ssmmessages:OpenDataChannel",
        "ssm:UpdateInstanceInformation"
      ],
      "Resource": "*"
    }
  ]
}
```

**Replace:**
- `S3_BUCKET_NAME` with your deployment bucket name
- `AWS_REGION` with your AWS region (e.g., `us-east-1`)
- `AWS_ACCOUNT_ID` with your 12-digit AWS account ID

## Step 4: Get the Role ARN

1. Go to **IAM** → **Roles** → Find `github-process-engine-deploy-role`
2. Copy the **ARN** (format: `arn:aws:iam::AWS_ACCOUNT_ID:role/github-process-engine-deploy-role`)

## Step 5: Configure GitHub Environment Secrets

### Via GitHub Web UI:

1. Go to your repository → **Settings** → **Environments**
2. Create/select environment: `process-engine-production` (for main branch) or `process-engine-staging` (for staging branch)
3. Click **Add secret**
4. Name: `AWS_ROLE_DEPLOY`
5. Value: Paste the role ARN from Step 4
6. Save

### Required Variables (also in Environments):

Add these as **Variables** (not secrets) in the same environment:

| Variable | Example Value | Purpose |
|----------|---------------|---------|
| `AWS_REGION` | `us-east-1` | AWS region for S3 and SSM |
| `S3_BUCKET_DEPLOYMENTS` | `my-deployments-bucket` | S3 bucket for storing wheel artifacts |
| `EC2_SERVICE_INSTANCE_ID` | `i-0123456789abcdef0` | Windows EC2 instance ID |
| `PROCESS_ENGINE_DESIGNER_URL` | `https://designer.example.com` | Designer frontend URL for notification links |

### Required Secrets (also in Environments):

| Secret | Purpose |
|--------|---------|
| `PROCESS_ENGINE_DB_URL_LOCAL` | MySQL connection for Windows host (e.g., `mysql+pymysql://user:pass@localhost:3306/process_engine`) |
| `PROCESS_ENGINE_SECRET_KEY` | Fernet key for secret encryption (64 chars, base64) |

## Step 6: Verify Windows EC2 Instance

The target EC2 instance must have:

1. **AWS Systems Manager (SSM) Agent** installed and running
   - Windows AMIs include this by default
   - Verify: EC2 dashboard → Instance → Check "Systems Manager" tab

2. **IAM Role with SSM Permissions**
   - The instance must have an IAM role that allows SSM commands
   - Attach AWS managed policy: `AmazonSSMManagedInstanceCore`

3. **Network Access**
   - SSM uses AWS Systems Manager Session Manager (no SSH/RDP needed)
   - Instance security group must allow outbound HTTPS (443) to AWS

## Step 7: Test the Configuration

Run the workflow manually:

1. Go to repository → **Actions** → **Process Engine Service**
2. Click **Run workflow** → Select branch → **Run workflow**
3. Monitor the `Configure AWS credentials using OIDC` step
4. If it passes, OIDC is configured correctly

## Troubleshooting

### Error: "Could not assume role with OIDC: Not authorized to perform sts:AssumeRoleWithWebIdentity"

**Causes:**
1. Role ARN in `AWS_ROLE_DEPLOY` secret is incorrect
2. Trust policy doesn't include GitHub OIDC provider
3. Repository reference in trust policy doesn't match actual repo
4. OIDC provider doesn't exist in IAM

**Fix:**
- Verify role ARN format: `arn:aws:iam::123456789012:role/role-name`
- Confirm OIDC provider exists: AWS IAM → Identity providers
- Re-check trust policy `sub` condition: should be `repo:kingdomdevtech/process-engine:*`

### Error: "User is not authorized to perform: s3:PutObject"

**Cause:** Permissions policy doesn't include S3 permissions or S3 bucket name is wrong

**Fix:**
- Add/update S3 bucket name in permissions policy
- Re-attach policy to role

### Error: "No SSM agent running on instance"

**Cause:** EC2 instance doesn't have SSM agent or doesn't have proper IAM role

**Fix:**
1. Check IAM role: Instance → Security → IAM role should include `AmazonSSMManagedInstanceCore`
2. Restart SSM agent on Windows instance:
   ```powershell
   Restart-Service -Name AmazonSSMAgent
   ```

## Workflow File Reference

The workflow expects these secrets/variables to be set in the `process-engine-production` and `process-engine-staging` environments:

```yaml
environment: ${{
  github.ref_name == 'main' && 'process-engine-production'
  || github.ref_name == 'staging' && 'process-engine-staging'
}}
```

**Secrets required:**
- `AWS_ROLE_DEPLOY` (ARN of the role created in Step 2)
- `PROCESS_ENGINE_DB_URL_LOCAL`
- `PROCESS_ENGINE_SECRET_KEY`

**Variables required:**
- `AWS_REGION`
- `S3_BUCKET_DEPLOYMENTS`
- `EC2_SERVICE_INSTANCE_ID`
- `PROCESS_ENGINE_DESIGNER_URL`

## Additional Resources

- [GitHub OIDC Documentation](https://docs.github.com/en/actions/deployment/security-hardening-your-deployments/about-security-hardening-with-openid-connect)
- [AWS OIDC Documentation](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_create_for-idp_oidc.html)
- [AWS Systems Manager Session Manager](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager.html)
