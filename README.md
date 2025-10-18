# Maintenance Prediction & Planning System

A production-ready ML system for predictive maintenance scheduling deployed on Azure.

## 🚀 Features

- **Machine Learning**: XGBoost models for failure prediction and maintenance interval optimization
- **Oracle Integration**: Extract and process maintenance data from Oracle databases
- **Azure Cloud**: Containerized deployment with automatic scheduling
- **Visualization**: Interactive plots and maintenance schedules
- **Alerts**: Email and SMS notifications for due maintenance

## 🏗️ Architecture
Oracle DB → Azure Container Instances → Azure Blob Storage
↓ ↓ ↓
Data Extract → ML Predictions → Plans & Visualizations

## 📋 Prerequisites

- Python 3.9+
- Azure CLI
- Oracle Client (for local development)
- Azure Subscription

## ⚙️ Setup

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/maintenance-predictor.git
   cd maintenance-predictor

2. **Install dependencies**
pip install -r requirements.txt

3. **Configure environment**
cp template.env .env
# Edit .env with your configuration

4. **Deploy to Azure**
chmod +x deploy-aci.sh
./deploy-aci.sh
