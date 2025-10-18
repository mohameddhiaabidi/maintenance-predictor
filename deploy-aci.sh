#!/bin/bash

echo "** Complete Deployment: Oracle with Data + Maintenance App **"

# Load environment variables
set -a
source .env
set +a

# Set variables with defaults
RESOURCE_GROUP="${AZURE_RESOURCE_GROUP:-maintenance-rg}"
LOCATION="${AZURE_LOCATION:-eastus}"
ORACLE_CONTAINER="oracle-xe-data"
APP_CONTAINER="maintenance-predictor"

echo "** Starting deployment to resource group: $RESOURCE_GROUP **"

# Check if resource group exists, create if not
echo "** Checking resource group...**"
if ! az group show --name $RESOURCE_GROUP &>/dev/null; then
    echo "Creating resource group..."
    az group create --name $RESOURCE_GROUP --location $LOCATION
else
    echo "Resource group already exists."
fi

# Clean up existing containers if they exist
echo "** Cleaning up existing containers... **"
az container delete --resource-group $RESOURCE_GROUP --name $APP_CONTAINER --yes --no-wait 2>/dev/null || true
az container delete --resource-group $RESOURCE_GROUP --name $ORACLE_CONTAINER --yes --no-wait 2>/dev/null || true

# Wait for deletions to complete
sleep 30

# Step 1: Create Azure File Share
echo "** Step 1: Setting up Azure File Share... **"

STORAGE_ACCOUNT="oraclefs$(date +%s)"
echo "** Creating storage account: $STORAGE_ACCOUNT **"

az storage account create \
  --name $STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --location $LOCATION \
  --sku Standard_LRS

az storage share create \
  --name oracledumps \
  --account-name $STORAGE_ACCOUNT

# Upload DMP file if it exists
if [ -f "GMAOS25082025.DMP" ]; then
    echo "** Uploading DMP file to Azure File Share... **"
    az storage file upload \
      --account-name $STORAGE_ACCOUNT \
      --share-name oracledumps \
      --source GMAOS25082025.DMP
else
    echo "⚠️  No DMP file found. Data import will be skipped."
    SKIP_DATA_IMPORT=true
fi

STORAGE_KEY=$(az storage account keys list \
  --resource-group $RESOURCE_GROUP \
  --account-name $STORAGE_ACCOUNT \
  --query "[0].value" \
  --output tsv)

# Step 2: Deploy Oracle
echo "** Step 2: Deploying Oracle Database... **"
az container create \
  --resource-group $RESOURCE_GROUP \
  --name $ORACLE_CONTAINER \
  --image container-registry.oracle.com/database/express:21.3.0-xe \
  --cpu 2 \
  --memory 4 \
  --ports 1521 \
  --os-type Linux \
  --ip-address Public \
  --environment-variables \
    ORACLE_PWD="${ORACLE_PASSWORD}" \
  --azure-file-volume-account-name $STORAGE_ACCOUNT \
  --azure-file-volume-account-key $STORAGE_KEY \
  --azure-file-volume-share-name oracledumps \
  --azure-file-volume-mount-path /mnt/dumps \
  --restart-policy Always

echo "** Waiting for Oracle to initialize... **"
sleep 180

ORACLE_IP=$(az container show --resource-group $RESOURCE_GROUP --name $ORACLE_CONTAINER --query "ipAddress.ip" -o tsv)
echo "Oracle IP: $ORACLE_IP"

# Step 3: Import Data (if DMP exists)
if [ "$SKIP_DATA_IMPORT" != "true" ]; then
    echo "** Step 3: Importing data into Oracle... **"
    
    sleep 30
    
    az container exec --resource-group $RESOURCE_GROUP --name $ORACLE_CONTAINER --exec-command "sqlplus -s system/${ORACLE_PASSWORD} << 'EOF'
CREATE OR REPLACE DIRECTORY dpump_dir AS '/mnt/dumps';
EXIT;
EOF" || echo "Directory creation might have failed"

    az container exec --resource-group $RESOURCE_GROUP --name $ORACLE_CONTAINER --exec-command "imp system/${ORACLE_PASSWORD} FILE=/mnt/dumps/GMAOS25082025.DMP FULL=Y LOG=/mnt/dumps/import.log" || echo "Import might have failed"
else
    echo "** Skipping data import **"
fi

# Step 4: Deploy Maintenance Application
echo "** Step 4: Deploying Maintenance Predictor Application... **"

APP_ACR_NAME="appacr$(date +%s)"
echo "** Creating Azure Container Registry: $APP_ACR_NAME **"
az acr create --resource-group $RESOURCE_GROUP --name $APP_ACR_NAME --sku Basic --admin-enabled true

echo "** Building application image... **"
az acr build --registry $APP_ACR_NAME --image $APP_CONTAINER:latest .

APP_STORAGE_ACCOUNT="maintstg$(date +%s)"
echo "** Creating storage account: $APP_STORAGE_ACCOUNT **"
az storage account create \
  --resource-group $RESOURCE_GROUP \
  --name $APP_STORAGE_ACCOUNT \
  --location $LOCATION \
  --sku Standard_LRS

STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
  --name $APP_STORAGE_ACCOUNT \
  --resource-group $RESOURCE_GROUP \
  --query "connectionString" \
  --output tsv)

APP_ACR_PASSWORD=$(az acr credential show --name $APP_ACR_NAME --query "passwords[0].value" --output tsv)

echo "** Deploying application... **"

# Build environment variables
ENV_VARS=(
    "ORACLE_USER=system"
    "ORACLE_HOST=$ORACLE_IP"
    "ORACLE_PORT=1521"
    "ORACLE_SERVICE=XE"
    "AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONNECTION_STRING"
    "EXTRACT_START=2025-01-01"
    "PLANNING_HORIZON_DAYS=90"
    "NUM_FUTURE_DATES=3"
    "SCHEDULE_TIME=06:00"
    "RUN_ON_STARTUP=true"
    "EMAIL_ENABLED=false"
    "SMS_ENABLED=false"
    "EMAIL_SMTP=smtp.gmail.com"
    "EMAIL_PORT=587"
)

# Add email if provided
if [ -n "$EMAIL_USER" ]; then
    ENV_VARS+=("EMAIL_USER=$EMAIL_USER")
    ENV_VARS+=("EMAIL_TO=${EMAIL_TO:-$EMAIL_USER}")
    ENV_VARS+=("EMAIL_ENABLED=true")
fi

# Build environment variables string
ENV_STRING=""
for var in "${ENV_VARS[@]}"; do
    ENV_STRING+=" --environment-variables $var"
done

# Build secure environment variables
SECURE_ENV_VARS=(
    "ORACLE_PASS=${ORACLE_PASSWORD}"
)

if [ -n "$EMAIL_PASS" ]; then
    SECURE_ENV_VARS+=("EMAIL_PASS=$EMAIL_PASS")
fi

SECURE_ENV_STRING=""
for var in "${SECURE_ENV_VARS[@]}"; do
    SECURE_ENV_STRING+=" --secure-environment-variables $var"
done

# Deploy the container
az container create \
  --resource-group $RESOURCE_GROUP \
  --name $APP_CONTAINER \
  --image $APP_ACR_NAME.azurecr.io/$APP_CONTAINER:latest \
  --cpu 2 \
  --memory 4 \
  --os-type Linux \
  --registry-username $APP_ACR_NAME \
  --registry-password "$APP_ACR_PASSWORD" \
  $ENV_STRING \
  $SECURE_ENV_STRING \
  --restart-policy Always

echo "** Deployment complete! **"
echo ""
echo "** Services: **"
echo "   Oracle: $ORACLE_IP:1521/XE"
echo "   App: $APP_CONTAINER"
echo "   Storage: $APP_STORAGE_ACCOUNT"
echo ""
echo "** Next: Configure .env file for email alerts and run pipeline **"
