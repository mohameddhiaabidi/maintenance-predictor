#!/bin/bash

echo "**** Setting up Azure environment..."

# Install Azure CLI
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash

# Login to Azure
az login

echo "*** Azure setup completed!"
echo "*** Next steps:"
echo "   1. Make scripts executable: chmod +x *.sh"
echo "   2. Run: ./deploy-aci.sh"
