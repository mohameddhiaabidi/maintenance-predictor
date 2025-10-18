Maintenance Prediction & Planning System
A production ML system for predictive maintenance scheduling on Azure Cloud.

🚀 Quick Start
bash
git clone https://github.com/yourusername/maintenance-predictor.git
cd maintenance-predictor
pip install -r requirements.txt
cp template.env .env
# Edit .env with your settings
chmod +x deploy-aci.sh
./deploy-aci.sh
⚙️ Setup
Create .env file:

env
AZURE_RESOURCE_GROUP=maintenance-rg
AZURE_LOCATION=eastus
ORACLE_PASSWORD=YourSecurePassword123
EMAIL_USER=your_email@gmail.com
EMAIL_PASS=your_app_password
EXTRACT_START=2025-01-01
PLANNING_HORIZON_DAYS=90
NUM_FUTURE_DATES=3
SCHEDULE_TIME=06:00
RUN_ON_STARTUP=true
🏗️ Architecture
Oracle DB → Azure Containers → Azure Storage → Email Alerts

Components:

Oracle Database (data source)

XGBoost ML models (failure prediction)

Azure Container Instances (deployment)

Azure Blob Storage (output storage)

Email/SMS alerts (notifications)

📊 Features
ML Models: XGBoost classifier + regressor

Maintenance Planning: Multi-interval scheduling with priorities

Visualization: Plots and schedules

Cloud Native: Containerized on Azure

Automated: Daily predictions at 6:00 AM

🔧 Usage
Check deployment:

bash
az container list --resource-group maintenance-rg -o table
View logs:

bash
az container exec --resource-group maintenance-rg --name maintenance-predictor --exec-command "tail -50 /tmp/simple.log"
Run manually:

bash
az container exec --resource-group maintenance-rg --name maintenance-predictor --exec-command "python main.py"
📁 Outputs
Azure Storage:

plans/maintenance_plan_YYYYMMDD_HHMMSS.xlsx

plots/schedule_plot_YYYYMMDD_HHMMSS.png

plots/confusion_matrix_YYYYMMDD_HHMMSS.png

plots/roc_curve_YYYYMMDD_HHMMSS.png

🛠️ Project Files
main.py - Main application & scheduler

maintenance_predictor.py - ML pipeline & models

azure_storage.py - Azure storage integration

deploy-aci.sh - Deployment script

Dockerfile - Container setup

requirements.txt - Python dependencies

🔍 Troubleshooting
Common issues:

Use az container exec instead of Azure logs

Check plot files: ls -la /tmp/*.png

Restart container: az container restart --resource-group maintenance-rg --name maintenance-predictor
