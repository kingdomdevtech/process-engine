# GitHub Environments Configuration

This document outlines the required environment variables and secrets for the Process Engine Service GitHub Actions workflows.

## Overview

Two separate workflows deploy different components to different hosts:

1. **Linux Container Deployment** (`process-engine-linux-deploy.yml`)
   - Deploys: Designer + API (same container)
   - Host: Linux EC2 instance (Docker)
   - Database: **Remote MySQL** (on a different server)
   - Port: 8080

2. **Windows Service Deployment** (`process-engine-windows-deploy.yml`)
   - Deploys: Engine worker service (claims jobs from queue)
   - Host: Windows EC2 instance
   - Database: **Localhost MySQL** (same server)
   - Communicates with: Linux API via shared database

Both workflows use GitHub Environments to manage different configurations for **staging** and **production** deployments. Each environment has its own set of secrets and variables.

- **Staging Environment**: `process-engine-staging` (triggered by pushes to `staging` branch)
- **Production Environment**: `process-engine-production` (triggered by pushes to `main` branch)

## Setup Instructions

### 1. Create GitHub Environments

In your repository settings (`Settings` → `Environments`):

1. Click **New environment**
2. Create `process-engine-staging`
3. Click **New environment** again
4. Create `process-engine-production`

### 2. Add Deployment Protection Rules (Recommended)

For production environment only:

- Go to `process-engine-production` environment settings
- Under "Deployment branches", select "Protected branches only"
- Require reviewers before deployment (optional but recommended)

---

## Shared Secrets (Required in Both Environments)

These secrets are required by both Windows and Linux deployments. Some secrets have host-specific values (Windows vs Linux), while others must be identical across both hosts.

### `AWS_ROLE_DEPLOY`

- **Type**: Secret
- **Description**: AWS IAM role ARN for GitHub OIDC federation
- **Format**: `arn:aws:iam::ACCOUNT_ID:role/github-process-engine-deploy`
- **Value Example**: `arn:aws:iam::123456789012:role/github-process-engine-deploy`
- **Required Permissions**:
  - `s3:PutObject` (upload to deployment bucket)
  - `s3:GetObject` (download from deployment bucket)
  - `ssm:SendCommand` (send commands to EC2 instances)
  - `ssm:GetCommandInvocation` (check command status)
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `AWS_ROLE_DEPLOY`
  4. Value: Your IAM role ARN

### `PROCESS_ENGINE_DB_URL_LOCAL` (Engine Service - Local Connection)

- **Type**: Secret
- **Description**: Database connection string for the engine service using local/localhost connection
- **Format**: `mysql+pymysql://username:password@host:port/database`
- **Value**: `mysql+pymysql://process_engine:password@localhost:3306/process_engine`
- **Why localhost**: The service connects to MySQL on the same machine via `localhost`
- **Environment-Specific**: Yes (different staging/production databases)
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_DB_URL_LOCAL`
  4. Value: `mysql+pymysql://process_engine:YOUR_PASSWORD@localhost:3306/process_engine`

### `PROCESS_ENGINE_DB_URL_REMOTE` (API Container - Remote Connection)

- **Type**: Secret
- **Description**: Database connection string for the API container using remote/network connection
- **Format**: `mysql+pymysql://username:password@host:port/database`
- **Value**: `mysql+pymysql://process_engine:password@MYSQL_HOST_IP:3306/process_engine`
- **Important**: Replace `MYSQL_HOST_IP` with the actual IP or hostname of the server running MySQL
- **Why remote host**: The container connects to MySQL on another server via network
- **Environment-Specific**: Yes (different staging/production databases, AND different host IPs per environment)
- **Example**: `mysql+pymysql://process_engine:mypassword@10.0.1.50:3306/process_engine`
- **Critical**: Both LOCAL and REMOTE must use the SAME database and credentials; only the host differs
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_DB_URL_REMOTE`
  4. Value: `mysql+pymysql://process_engine:YOUR_PASSWORD@MYSQL_HOST_IP:3306/process_engine`

### `PROCESS_ENGINE_SECRET_KEY` (Shared Across Windows and Linux)

- **Type**: Secret
- **Description**: Encryption key for storing secrets (Fernet format)
- **Format**: Base64-encoded 32-byte key
- **Generation**: Use `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- **Critical**: Must be **byte-identical** on **BOTH Windows AND Linux** within the same environment
- **Rotation**: Cannot be rotated without re-encrypting all stored secrets
- **Must be the same**: Within staging env, Windows and Linux use same key. Within production env, Windows and Linux use the same key (but staging and prod can differ).
- **Consequence**: If keys differ between Windows and Linux in the same environment:
  - Windows cannot decrypt secrets encrypted by Linux
  - Linux cannot decrypt secrets encrypted by Windows
  - Runs will fail with encryption errors
- **How to Set**:
  1. Generate a new key (only once per environment)
  2. Go to environment settings
  3. Click **Add secret**
  4. Name: `PROCESS_ENGINE_SECRET_KEY`
  5. Value: Your generated key
  6. **Store this value securely** (save in password manager)
  7. **Use the SAME value for both Windows and Linux deployments in that environment**

---

## Environment-Specific Variables

These variables should differ between staging and production environments.

### `AWS_REGION`

- **Type**: Variable
- **Description**: AWS region where your infrastructure resides
- **Example Value**: `us-east-1` (or your desired region)
- **Required**: Yes

### `S3_BUCKET_DEPLOYMENTS` (Windows only)

- **Type**: Variable
- **Description**: S3 bucket name for storing deployment packages (Windows service only)
- **Example Value (Staging)**: `deployments-staging`
- **Example Value (Production)**: `deployments-prod`
- **Required by**: `process-engine-windows-deploy.yml`
- **Bucket Structure**:
  ```
  s3://bucket-name/
  └── process-engine/
      ├── process-engine-staging.zip
      └── process-engine-prod.zip
  ```
- **S3 Permissions Required**:
  - `s3:PutObject` - Upload deployment packages
  - `s3:GetObject` - Download packages on Windows servers
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `S3_BUCKET_DEPLOYMENTS`
  4. Value: Your S3 bucket name

### `ECR_REGISTRY` (Linux only)

- **Type**: Variable
- **Description**: Amazon ECR registry URL for container images
- **Format**: `ACCOUNT_ID.dkr.ecr.REGION.amazonaws.com`
- **Example Value**: `123456789012.dkr.ecr.us-east-1.amazonaws.com`
- **Required by**: `process-engine-linux-deploy.yml`
- **How to Find**:
  1. Go to AWS ECR Console
  2. View your registry details
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `ECR_REGISTRY`
  4. Value: Your ECR registry URL

### `ECR_REPOSITORY_DESIGNER` (Linux only)

- **Type**: Variable
- **Description**: ECR repository name for the Designer + API container
- **Format**: `process-engine-designer` or similar
- **Example Value**: `process-engine-designer`
- **Required by**: `process-engine-linux-deploy.yml`
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `ECR_REPOSITORY_DESIGNER`
  4. Value: Your repository name

### `EC2_SERVICE_INSTANCE_ID` (Windows)

- **Type**: Variable
- **Description**: EC2 instance ID of the Windows server running the process engine worker service
- **Format**: `i-0123456789abcdef0`
- **Example Value (Staging)**: `i-0987654321fedcba0`
- **Example Value (Production)**: `i-0123456789abcdef0`
- **Required by**: `process-engine-windows-deploy.yml`
- **How to Find**:
  1. Go to AWS EC2 Dashboard
  2. Select your Windows instance
  3. Copy the Instance ID
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `EC2_SERVICE_INSTANCE_ID`
  4. Value: Your Windows EC2 instance ID

### `EC2_WEB_INSTANCE_ID` (Designer + API)

- **Type**: Variable
- **Description**: EC2 instance ID of the Linux server running the Designer + API container
- **Format**: `i-0123456789abcdef0`
- **Example Value (Staging)**: `i-1234567890abcdef0`
- **Example Value (Production)**: `i-fedcba0987654321`
- **Required by**: `process-engine-linux-deploy.yml`
- **How to Find**:
  1. Go to AWS EC2 Dashboard
  2. Select your Linux instance
  3. Copy the Instance ID
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `EC2_WEB_INSTANCE_ID`
  4. Value: Your Linux EC2 instance ID

### `PROCESS_ENGINE_DESIGNER_URL`

- **Type**: Variable
- **Description**: URL where the designer is accessible (for run notification links and references)
- **Format**: Full HTTPS URL without trailing slash
- **Example Value (Staging)**: `https://staging.designer.example.com`
- **Example Value (Production)**: `https://designer.example.com`
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_DESIGNER_URL`
  4. Value: Your designer URL

---

## Designer & API Container Secrets and Variables

The Designer (React frontend) and API (FastAPI backend) run together in the Linux container and share configuration.

### `PROCESS_ENGINE_PUBLIC_URL` (API Origin)

- **Type**: Variable
- **Description**: The API's own public URL, used for OIDC callback registration
- **Format**: Full HTTPS URL without trailing slash
- **Example Value (Staging)**: `https://staging-api.example.com`
- **Example Value (Production)**: `https://api.example.com`
- **Important**: Must match the URL registered with your SSO provider (Google, Entra, etc.)
- **When Different from Designer URL**: If you host the Designer and API separately, this is where the API lives
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_PUBLIC_URL`
  4. Value: Your API's public URL

### `PROCESS_ENGINE_AUTH_TOKEN` (Static API Token)

- **Type**: Secret
- **Description**: Static API token for machine-to-machine authentication and bootstrap admin access
- **Format**: Random alphanumeric string (recommended 32+ characters)
- **Generation**: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
- **Environment-Specific**: Yes (different staging/production tokens)
- **Used By**:
  - Bootstrap/initial admin user creation
  - Automation scripts and CI/CD pipelines
  - Machine-to-machine API calls (not human users)
- **Note**: Human users receive session tokens via `/api/auth/login`; this is the admin override
- **How to Set**:
  1. Generate a secure token
  2. Go to environment settings
  3. Click **Add secret**
  4. Name: `PROCESS_ENGINE_AUTH_TOKEN`
  5. Value: Your generated token

### `VITE_API_BASE` (Designer Build Variable)

- **Type**: Variable (Build-time, not runtime)
- **Description**: API base URL that the Designer (React) uses for all API calls
- **Format**: Full URL with protocol, no trailing slash
- **Default**: `/api` (relative path, assumes same origin)
- **Example Value (Staging)**: `https://staging-api.example.com/api`
- **Example Value (Production)**: `https://api.example.com/api`
- **When to Change**: Only if Designer and API are hosted on different origins
- **Scope**: This is baked into the Docker image at build time
- **How to Set** (in GitHub Actions):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `VITE_API_BASE`
  4. Value: Your API base URL (or leave unset for `/api`)
  5. The workflow uses this to build the Docker image with correct API endpoint

### SSO (OAuth/OIDC) Configuration

The Designer supports Google and Azure Entra (Microsoft) SSO. Set these only if you want SSO enabled.

#### `PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID`

- **Type**: Secret
- **Description**: Google OAuth 2.0 Client ID for SSO
- **How to Obtain**:
  1. Go to [Google Cloud Console](https://console.cloud.google.com/)
  2. Create or select a project
  3. Enable Google+ API
  4. Create OAuth 2.0 credentials (Web Application)
  5. Add authorized redirect URI: `{PROCESS_ENGINE_PUBLIC_URL}/auth/callback/google`
  6. Copy the Client ID
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID`
  4. Value: Your Client ID

#### `PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET`

- **Type**: Secret
- **Description**: Google OAuth 2.0 Client Secret
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET`
  4. Value: Your Client Secret

#### `PROCESS_ENGINE_OIDC_ENTRA_CLIENT_ID`

- **Type**: Secret
- **Description**: Azure Entra (Microsoft) OAuth 2.0 Client ID for SSO
- **How to Obtain**:
  1. Go to [Azure Portal](https://portal.azure.com/) → App registrations
  2. Create a new application
  3. Add Redirect URI: `{PROCESS_ENGINE_PUBLIC_URL}/auth/callback/entra`
  4. Copy the Application (Client) ID
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_OIDC_ENTRA_CLIENT_ID`
  4. Value: Your Client ID

#### `PROCESS_ENGINE_OIDC_ENTRA_CLIENT_SECRET`

- **Type**: Secret
- **Description**: Azure Entra Client Secret
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_OIDC_ENTRA_CLIENT_SECRET`
  4. Value: Your Client Secret

#### `PROCESS_ENGINE_OIDC_ENTRA_TENANT_ID`

- **Type**: Secret
- **Description**: Azure Entra Tenant ID
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_OIDC_ENTRA_TENANT_ID`
  4. Value: Your Tenant ID

#### `PROCESS_ENGINE_SSO_AUTO_PROVISION`

- **Type**: Variable
- **Description**: Automatically create users from SSO login if they don't exist
- **Default**: `false` (require users to be manually created first)
- **Allowed Values**: `true` or `false`
- **When to Enable**:
  - `true`: Anyone who can log in with your SSO provider gets an account automatically
  - `false`: Only pre-existing users can log in (safer for private instances)
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_SSO_AUTO_PROVISION`
  4. Value: `true` or `false`

### Email/Notifications Configuration

The API can send email notifications for process runs. Configure these if you want notifications enabled.

#### `PROCESS_ENGINE_MAIL_PROVIDER`

- **Type**: Variable
- **Description**: Email provider for sending notifications
- **Allowed Values**: `smtp` or `ses` (Amazon SES)
- **Default**: Not set (notifications disabled)
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_MAIL_PROVIDER`
  4. Value: `smtp` or `ses`

#### `PROCESS_ENGINE_MAIL_FROM` (Both SMTP and SES)

- **Type**: Variable
- **Description**: Email address that notifications appear to come from
- **Format**: Email address
- **Example**: `noreply@example.com`
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_MAIL_FROM`
  4. Value: Your sender email

#### SMTP Configuration (if using SMTP provider)

##### `PROCESS_ENGINE_MAIL_SMTP_HOST`

- **Type**: Variable
- **Description**: SMTP server hostname
- **Example**: `smtp.gmail.com` or `mail.example.com`
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_MAIL_SMTP_HOST`
  4. Value: Your SMTP host

##### `PROCESS_ENGINE_MAIL_SMTP_PORT`

- **Type**: Variable
- **Description**: SMTP server port
- **Default**: `587` (TLS) or `465` (SSL)
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_MAIL_SMTP_PORT`
  4. Value: Port number

##### `PROCESS_ENGINE_MAIL_SMTP_USERNAME`

- **Type**: Secret
- **Description**: SMTP authentication username
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_MAIL_SMTP_USERNAME`
  4. Value: Your SMTP username

##### `PROCESS_ENGINE_MAIL_SMTP_PASSWORD`

- **Type**: Secret
- **Description**: SMTP authentication password
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_MAIL_SMTP_PASSWORD`
  4. Value: Your SMTP password

##### `PROCESS_ENGINE_MAIL_SMTP_TLS`

- **Type**: Variable
- **Description**: Use TLS encryption for SMTP
- **Default**: `true`
- **Allowed Values**: `true` or `false`
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_MAIL_SMTP_TLS`
  4. Value: `true` or `false`

#### SES Configuration (if using AWS SES provider)

##### `PROCESS_ENGINE_MAIL_SES_REGION`

- **Type**: Variable
- **Description**: AWS region where SES is configured
- **Example**: `us-east-1`
- **How to Set**:
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_MAIL_SES_REGION`
  4. Value: Your AWS region

##### `PROCESS_ENGINE_MAIL_SES_ACCESS_KEY_ID`

- **Type**: Secret
- **Description**: AWS IAM access key for SES
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_MAIL_SES_ACCESS_KEY_ID`
  4. Value: Your access key

##### `PROCESS_ENGINE_MAIL_SES_SECRET_ACCESS_KEY`

- **Type**: Secret
- **Description**: AWS IAM secret access key for SES
- **How to Set**:
  1. Go to environment settings
  2. Click **Add secret**
  3. Name: `PROCESS_ENGINE_MAIL_SES_SECRET_ACCESS_KEY`
  4. Value: Your secret key

---

## Optional Environment-Specific Variables

These variables have sensible defaults and only need to be set if you want to customize behavior.

### `PROCESS_ENGINE_WORK_DIR`

- **Type**: Variable
- **Description**: Directory where the process engine stores working files
- **Default**: `C:\ProcessEngine\workdir`
- **Format**: Windows path
- **Example**: `C:\apps\process-engine\workdir`
- **Recommendation**: Set to a location with sufficient disk space and backups
- **How to Set** (if customizing):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_WORK_DIR`
  4. Value: Your desired path

### `PROCESS_ENGINE_STEP_WORKERS`

- **Type**: Variable
- **Description**: Number of concurrent worker threads for step execution
- **Default**: `8`
- **Recommended**:
  - Staging: `4` (or number of CPU cores / 2)
  - Production: `8` or higher (based on server capacity)
- **Tuning**: Set to (CPU cores - 1) for optimal throughput
- **How to Set** (if customizing):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_STEP_WORKERS`
  4. Value: Number of workers

### `PROCESS_ENGINE_QUEUE_POLL_SECONDS`

- **Type**: Variable
- **Description**: How frequently the engine polls the job queue (in seconds)
- **Default**: `2.0`
- **Recommended**:
  - Staging: `2.0` (responsive, less taxing)
  - Production: `1.0` (responsive) to `2.0` (conservative)
- **Trade-off**: Lower values = faster job pickup but higher DB load
- **How to Set** (if customizing):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_QUEUE_POLL_SECONDS`
  4. Value: Seconds as decimal (e.g., `2.0`)

### `PROCESS_ENGINE_LOG_LEVEL`

- **Type**: Variable
- **Description**: Logging verbosity level
- **Default**: `INFO`
- **Allowed Values**: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- **Recommended**:
  - Staging: `DEBUG` (detailed logging for troubleshooting)
  - Production: `INFO` (balance between detail and performance)
- **How to Set** (if customizing):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_LOG_LEVEL`
  4. Value: Log level

### `PROCESS_ENGINE_SERVICE_NAME`

- **Type**: Variable
- **Description**: Windows service name for the process engine worker
- **Default**: `ProcessEngineWorker`
- **Recommended**:
  - Staging: `ProcessEngineWorker-Staging` or `ProcessEngineWorker-ST`
  - Production: `ProcessEngineWorker` or `ProcessEngineWorker-Prod`
- **Note**: Service name must be unique on the Windows server
- **How to Set** (if customizing):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_SERVICE_NAME`
  4. Value: Desired service name

### `PROCESS_ENGINE_VENV_PATH`

- **Type**: Variable
- **Description**: Full path to the Python virtual environment on the Windows server
- **Default**: `C:\apps\releases\process-engine\{tag}\venv` (tag = `staging` or `prod`)
- **Format**: Windows path ending with `\venv`
- **Example**: `C:\apps\python-envs\process-engine-venv`
- **How to Set** (if customizing):
  1. Go to environment settings
  2. Click **Add variable**
  3. Name: `PROCESS_ENGINE_VENV_PATH`
  4. Value: Full path to venv

---

## Deployment Architecture & Server Setup

### Windows Server (Engine Service with Local MySQL)

The Windows host runs:

1. **Process Engine Service** — Claims jobs from the shared database, executes steps, runs scheduled processes
2. **MySQL Database Server** — Local instance, shared with the Linux container via network connection

**Pre-Deployment Checklist:**

- [ ] Windows Server 2016+ with SSM agent installed
- [ ] Python 3.11 installed (or use `py -3.11` launcher)
- [ ] MySQL Server installed and running on localhost:3306
  - Database created: `process_engine`
  - Database user created: `process_engine` with appropriate password
  - Database must be accessible from both localhost (Windows service) AND from the Linux host (Docker container)
  - MySQL must listen on `0.0.0.0` or the Linux host's IP address, not just localhost
- [ ] Windows Firewall allows MySQL port 3306 from Linux host (or disabled for testing)
- [ ] Sufficient disk space in `C:\ProcessEngine\workdir` for step files
- [ ] IAM instance profile attached for SSM access and S3 deployment bucket reads

**Database Setup (Windows):**

```sql
-- On the Windows MySQL server, allow connections from the Linux host IP
-- Find your Linux host IP (e.g., 10.0.1.100) and replace it below

CREATE USER 'process_engine'@'%' IDENTIFIED BY 'your_password';
CREATE DATABASE process_engine;
GRANT ALL PRIVILEGES ON process_engine.* TO 'process_engine'@'%';
FLUSH PRIVILEGES;

-- Or more restrictively, allow specific Linux IP:
-- CREATE USER 'process_engine'@'10.0.1.100' IDENTIFIED BY 'your_password';
```

**PROCESS_ENGINE_DB_URL for Windows:**

```
mysql+pymysql://process_engine:your_password@localhost:3306/process_engine
```

**Deployment Flow:**

1. Changes pushed to `main`/`staging` branch
2. GitHub Actions builds wheels and creates deployment package
3. Package uploaded to S3
4. SSM sends PowerShell script to Windows instance
5. Script downloads package from S3, extracts, installs to `C:\apps\releases\process-engine\{tag}\`
6. Windows service created and started (`ProcessEngineWorker`)

### Linux Server (Designer + API Container, connects to Windows MySQL)

The Linux host runs:

1. **Docker Container** with:
   - Designer (React frontend, built to static HTML)
   - Process Engine API (FastAPI, serves the designer + REST API)
   - nginx (reverse proxy, serves designer and proxies `/api` requests)

**Pre-Deployment Checklist:**

- [ ] Linux EC2 instance (any distro) with SSM agent installed
- [ ] Docker and Docker Compose installed and running
- [ ] AWS ECR repository created: `process-engine-api` (or your chosen name)
- [ ] Environment file created at `/etc/process-engine/linux-api.env`
- [ ] Volume created: `docker volume create process-engine-data`
- [ ] Sufficient disk space in `/data` volume for SQLite fallback and keys
- [ ] IAM instance profile attached for SSM access and ECR registry access
- [ ] Network access to Windows MySQL server (firewall allows port 3306)

**Environment File Setup (Linux):**
Create `/etc/process-engine/linux-api.env` with:

```bash
# Must point to the MySQL on the Windows host, NOT localhost
# Replace WINDOWS_HOST_IP with the actual Windows server IP or hostname
PROCESS_ENGINE_DB_URL=mysql+pymysql://process_engine:your_password@WINDOWS_HOST_IP:3306/process_engine

# Must be identical on Windows and Linux hosts
PROCESS_ENGINE_SECRET_KEY=your_fernet_key

# Deployment config
PROCESS_ENGINE_AUTH_TOKEN=your_api_token
PROCESS_ENGINE_PUBLIC_URL=https://your-domain.com
PROCESS_ENGINE_DESIGNER_URL=https://your-domain.com

# Optional: SSO configuration
# PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID=...
# PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET=...
```

**PROCESS_ENGINE_DB_URL for Linux:**

```
mysql+pymysql://process_engine:your_password@10.0.1.50:3306/process_engine
# Replace 10.0.1.50 with actual Windows server IP
```

**Deployment Flow:**

1. Changes pushed to `main`/`staging` branch
2. GitHub Actions builds Docker image
3. Image tagged and pushed to ECR
4. SSM sends shell script to Linux instance
5. Script logs into ECR, stops old container, pulls new image, runs with environment file

### Database Coordination & Connection Details

Both hosts connect to the **same MySQL instance** (on Windows) using **different connection strings**:

| Host               | Connection String    | Secret                         | Why                                  |
| ------------------ | -------------------- | ------------------------------ | ------------------------------------ |
| **Engine Service** | `localhost:3306`     | `PROCESS_ENGINE_DB_URL_LOCAL`  | Local connection (same server)       |
| **API Container**  | `MYSQL_HOST_IP:3306` | `PROCESS_ENGINE_DB_URL_REMOTE` | Remote connection (different server) |

**What They Share:**

- Same database name: `process_engine`
- Same username/password
- Same `job_queue` table (Windows claims jobs, Linux enqueues them)
- Same `process_instances` table (Windows updates runs, Linux reads status)
- Same `secrets`, `processes`, `users`, and `settings` tables
- Same `PROCESS_ENGINE_SECRET_KEY` for encryption/decryption

**Critical Requirements:**

1. **Both secrets must use the same username and password**
   - `PROCESS_ENGINE_DB_URL_LOCAL` and `PROCESS_ENGINE_DB_URL_REMOTE` differ only in the host part
   - Example: `process_engine:mypassword` is identical in both URLs
2. **`PROCESS_ENGINE_SECRET_KEY` must be byte-identical on both Windows and Linux**
   - Within the same environment (staging or production)
   - Windows cannot decrypt Linux-encrypted secrets or vice versa if the key differs
   - If keys mismatch, runs will fail with encryption errors
3. **Windows MySQL must allow remote connections from Linux host**
   - MySQL bind must be `0.0.0.0` or include Linux host IP
   - Firewall must allow port 3306 from Linux host
4. **Use same credentials in both URLs**
   - Windows: `mysql+pymysql://process_engine:password@localhost:3306/process_engine`
   - Linux: `mysql+pymysql://process_engine:password@10.0.1.50:3306/process_engine` (password is same)

---

## Quick Reference Table

### Legend

- ✅ = Required for this host/environment
- — = Not applicable
- **Same** = Use same value in staging & production
- **Different** = Use different values per environment
- **Optional** = Has sensible default
- **Generation** = How to create the secret value (shown where applicable)

### AWS & Shared Infrastructure

| Name              | Type     | Windows | Designer/API | Generation | Notes                                      |
| ----------------- | -------- | ------- | ------------ | ---------- | ------------------------------------------ |
| `AWS_ROLE_DEPLOY` | Secret   | ✅      | ✅           | AWS IAM    | See "AWS OIDC Setup" section below         |
| `AWS_REGION`      | Variable | ✅      | ✅           | Manual     | Usually same region (same in staging/prod) |

### Database Coordination

| Name                           | Type   | Windows | Designer/API | Env-Specific | Generation                                                                                  | Notes                                           |
| ------------------------------ | ------ | ------- | ------------ | ------------ | ------------------------------------------------------------------------------------------- | ----------------------------------------------- |
| `PROCESS_ENGINE_DB_URL_LOCAL`  | Secret | ✅      | —            | Different    | Manual                                                                                      | `mysql+pymysql://user:pass@localhost:3306/db`   |
| `PROCESS_ENGINE_DB_URL_REMOTE` | Secret | —       | ✅           | Different    | Manual                                                                                      | `mysql+pymysql://user:pass@HOST_IP:3306/db`     |
| `PROCESS_ENGINE_SECRET_KEY`    | Secret | ✅      | ✅           | One key      | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **Must be identical between both hosts in env** |

### Infrastructure & Deployment

| Name                      | Type     | Windows | Designer/API | Env-Specific | Generation | Notes                        |
| ------------------------- | -------- | ------- | ------------ | ------------ | ---------- | ---------------------------- |
| `S3_BUCKET_DEPLOYMENTS`   | Variable | ✅      | —            | Different    | AWS S3     | Windows deployment only      |
| `ECR_REGISTRY`            | Variable | —       | ✅           | Same         | AWS ECR    | Designer/API deployment only |
| `ECR_REPOSITORY_DESIGNER` | Variable | —       | ✅           | Same         | Manual     | Designer/API deployment only |
| `EC2_SERVICE_INSTANCE_ID` | Variable | ✅      | —            | Different    | AWS EC2    | Windows engine host ID       |
| `EC2_WEB_INSTANCE_ID`     | Variable | —       | ✅           | Different    | AWS EC2    | Designer/API web host ID     |

### Designer & API URLs

| Name                          | Type     | Windows | Designer/API  | Env-Specific | Generation                                                     | Notes                        |
| ----------------------------- | -------- | ------- | ------------- | ------------ | -------------------------------------------------------------- | ---------------------------- |
| `PROCESS_ENGINE_DESIGNER_URL` | Variable | ✅      | ✅            | Different    | Manual                                                         | User-facing Designer URL     |
| `PROCESS_ENGINE_PUBLIC_URL`   | Variable | ✅      | ✅            | Different    | Manual                                                         | API's public URL (OIDC)      |
| `PROCESS_ENGINE_AUTH_TOKEN`   | Secret   | ✅      | ✅            | Different    | `python -c "import secrets; print(secrets.token_urlsafe(32))"` | Static API token (bootstrap) |
| `VITE_API_BASE`               | Variable | —       | ✅ (optional) | Optional     | N/A                                                            | Designer's API endpoint      |

### Single Sign-On (Optional)

| Name                                       | Type     | Designer/API  | Generation | Notes                |
| ------------------------------------------ | -------- | ------------- | ---------- | -------------------- |
| `PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_ID`     | Secret   | ✅ (optional) | Google API | Google OAuth         |
| `PROCESS_ENGINE_OIDC_GOOGLE_CLIENT_SECRET` | Secret   | ✅ (optional) | Google API | Google OAuth         |
| `PROCESS_ENGINE_OIDC_ENTRA_CLIENT_ID`      | Secret   | ✅ (optional) | Azure AD   | Azure Entra OAuth    |
| `PROCESS_ENGINE_OIDC_ENTRA_CLIENT_SECRET`  | Secret   | ✅ (optional) | Azure AD   | Azure Entra OAuth    |
| `PROCESS_ENGINE_OIDC_ENTRA_TENANT_ID`      | Secret   | ✅ (optional) | Azure AD   | Azure Entra OAuth    |
| `PROCESS_ENGINE_SSO_AUTO_PROVISION`        | Variable | ✅ (optional) | Manual     | Auto-create from SSO |

### Email Notifications (Optional)

**Common:**

| Name                           | Type     | Designer/API  | Generation | Notes           |
| ------------------------------ | -------- | ------------- | ---------- | --------------- |
| `PROCESS_ENGINE_MAIL_PROVIDER` | Variable | ✅ (optional) | Manual     | `smtp` or `ses` |
| `PROCESS_ENGINE_MAIL_FROM`     | Variable | ✅ (optional) | Manual     | Sender email    |

**SMTP Configuration:**

| Name                                | Type     | Designer/API  | Generation | Notes         |
| ----------------------------------- | -------- | ------------- | ---------- | ------------- |
| `PROCESS_ENGINE_MAIL_SMTP_HOST`     | Variable | ✅ (optional) | Manual     | Hostname      |
| `PROCESS_ENGINE_MAIL_SMTP_PORT`     | Variable | ✅ (optional) | Manual     | 587 or 465    |
| `PROCESS_ENGINE_MAIL_SMTP_USERNAME` | Secret   | ✅ (optional) | SMTP Svc   | Credentials   |
| `PROCESS_ENGINE_MAIL_SMTP_PASSWORD` | Secret   | ✅ (optional) | SMTP Svc   | Credentials   |
| `PROCESS_ENGINE_MAIL_SMTP_TLS`      | Variable | ✅ (optional) | Manual     | Default: true |

**AWS SES Configuration:**

| Name                                        | Type     | Designer/API  | Generation | Notes      |
| ------------------------------------------- | -------- | ------------- | ---------- | ---------- |
| `PROCESS_ENGINE_MAIL_SES_REGION`            | Variable | ✅ (optional) | AWS SES    | AWS region |
| `PROCESS_ENGINE_MAIL_SES_ACCESS_KEY_ID`     | Secret   | ✅ (optional) | AWS IAM    | AWS creds  |
| `PROCESS_ENGINE_MAIL_SES_SECRET_ACCESS_KEY` | Secret   | ✅ (optional) | AWS IAM    | AWS creds  |

### Windows Engine Options (Optional)

| Name                                | Type     | Windows | Generation | Notes                               |
| ----------------------------------- | -------- | ------- | ---------- | ----------------------------------- |
| `PROCESS_ENGINE_WORK_DIR`           | Variable | ✅      | Manual     | Default: `C:\ProcessEngine\workdir` |
| `PROCESS_ENGINE_STEP_WORKERS`       | Variable | ✅      | Manual     | Default: `8`                        |
| `PROCESS_ENGINE_QUEUE_POLL_SECONDS` | Variable | ✅      | Manual     | Default: `2.0`                      |
| `PROCESS_ENGINE_LOG_LEVEL`          | Variable | ✅      | Manual     | Default: `INFO`                     |
| `PROCESS_ENGINE_SERVICE_NAME`       | Variable | ✅      | Manual     | Default: `ProcessEngineWorker`      |
| `PROCESS_ENGINE_VENV_PATH`          | Variable | ✅      | Manual     | Computed if not set                 |

---

## AWS OIDC Setup (One-time Setup)

### Prerequisites

- AWS Account with IAM permissions to create roles
- GitHub repository owner access

### Steps

1. **Create OIDC Identity Provider in AWS**

   ```bash
   aws iam create-open-id-connect-provider \
     --url https://token.actions.githubusercontent.com \
     --client-id-list sts.amazonaws.com \
     --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
   ```

2. **Create IAM Role for GitHub**

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Principal": {
           "Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
         },
         "Action": "sts:AssumeRoleWithWebIdentity",
         "Condition": {
           "StringEquals": {
             "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
             "token.actions.githubusercontent.com:sub": "repo:ORG_NAME/REPO_NAME:ref:refs/heads/*"
           }
         }
       }
     ]
   }
   ```

3. **Attach Policy to Role**

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject"],
         "Resource": "arn:aws:s3:::deployment-bucket/*"
       },
       {
         "Effect": "Allow",
         "Action": ["ssm:SendCommand", "ssm:GetCommandInvocation"],
         "Resource": "*"
       }
     ]
   }
   ```

4. **Save Role ARN** and add to secrets as `AWS_ROLE_DEPLOY`

---

## Verification Checklist

- [ ] `process-engine-staging` environment created
- [ ] `process-engine-production` environment created
- [ ] `AWS_ROLE_DEPLOY` secret added to both environments (same value)
- [ ] `PROCESS_ENGINE_DB_URL` secret added to both environments (different values)
- [ ] `PROCESS_ENGINE_SECRET_KEY` secret added to both environments (same value)
- [ ] `AWS_REGION` variable added to both environments
- [ ] `S3_BUCKET_DEPLOYMENTS` variable added to both environments (different values)
- [ ] `EC2_SERVICE_INSTANCE_ID` variable added to both environments (different values)
- [ ] `PROCESS_ENGINE_DESIGNER_URL` variable added to both environments (different values)
- [ ] OIDC trust relationship configured in AWS IAM role
- [ ] S3 bucket created with proper permissions
- [ ] Windows EC2 instances are configured with SSM agent and proper IAM role
- [ ] Database instances are accessible from Windows servers

---

## Troubleshooting

### "Secret not found" error in workflow

- Verify secret is added to the correct environment
- Check secret name spelling (case-sensitive)
- Ensure you're viewing the right environment settings

### "AWS OIDC error" during deployment

- Verify `AWS_ROLE_DEPLOY` ARN is correct
- Check OIDC provider is created in AWS
- Verify role trust policy includes GitHub repository
- Confirm IAM permissions are attached to role

### "EC2 instance not found" error

- Verify `EC2_SERVICE_INSTANCE_ID` is correct
- Ensure EC2 instance has SSM agent running
- Check IAM role on EC2 has SSM permissions
- Verify AWS region is correct

### Windows service fails to start

- Check `PROCESS_ENGINE_LOG_LEVEL` is set to `DEBUG`
- Verify `PROCESS_ENGINE_DB_URL` is correct and database is accessible
- Ensure `PROCESS_ENGINE_SECRET_KEY` matches the encryption key used
- Check Windows event logs on the server

---

## Maintenance

### Rotating the Secret Key

This is complex and requires downtime. Generally not recommended unless compromised:

1. Generate a new key
2. Create database backup
3. Re-encrypt all secrets with new key
4. Update key in all environments
5. Restart all engine instances

### Updating Database URL

After updating the database:

1. Update `PROCESS_ENGINE_DB_URL` in both environments
2. Test connection on a staging deployment first
3. Deploy to production

### Adding New Process Engine Instances

1. Launch new EC2 instance with SSM agent
2. Add new instance ID to appropriate environments
3. Workflow will deploy to all configured instances
