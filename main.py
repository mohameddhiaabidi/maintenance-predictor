# main.py
import os
import logging
import schedule
import time
import threading
from datetime import datetime

# Import all your functions
from maintenance_predictor import (
    extract_from_oracle, preprocess, build_features, train_models,
    generate_planning, plot_schedule, send_email_alert, send_sms_alert,
    plot_confusion_matrix, plot_roc_curve, plot_pr_curve  # Add these imports
)
from azure_storage import AzureStorageHelper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def run_maintenance_pipeline():
    """Main maintenance prediction pipeline"""
    try:
        logger.info("🚀 Starting maintenance prediction pipeline...")
        
        # Get configuration from environment
        extract_start = os.getenv("EXTRACT_START", "2025-01-01")
        extract_end = datetime.now().strftime("%Y-%m-%d")
        planning_horizon = int(os.getenv("PLANNING_HORIZON_DAYS", "90"))
        
        # 1) Extract data from Oracle
        logger.info("📊 Step 1: Extracting data from Oracle...")
        raw_data = extract_from_oracle(extract_start, extract_end)
        logger.info(f"✅ Extracted {len(raw_data)} records")
        
        # 2) Preprocess
        logger.info("🔧 Step 2: Preprocessing data...")
        processed_data = preprocess(raw_data)
        
        # 3) Build features
        logger.info("🎯 Step 3: Building features...")
        featured_data = build_features(processed_data)
        
        # 4) Train models
        logger.info("🤖 Step 4: Training models...")
        clf, reg, features = train_models(featured_data)
        
        # 5) Generate planning
        logger.info("📅 Step 5: Generating maintenance plan...")
        plan = generate_planning(
            featured_data, clf, reg, features,
            horizon_days=planning_horizon,
            num_future=int(os.getenv("NUM_FUTURE_DATES", "3"))
        )
        
        # 6) Save to Azure Storage
        logger.info("💾 Step 6: Saving to Azure Storage...")
        storage_helper = AzureStorageHelper()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        plan_filename = f"maintenance_plan_{timestamp}.xlsx"
        storage_helper.save_dataframe(plan, "plans", plan_filename)
        
        # 7) Generate and upload ALL plots
        logger.info("📊 Step 7: Generating and uploading plots...")
        
        # Generate schedule plot (this will save to /tmp/schedule_plot.png)
        try:
            plot_schedule(plan, horizon_days=planning_horizon)
            logger.info("✅ Schedule plot generated")
        except Exception as e:
            logger.error(f"❌ Failed to generate schedule plot: {e}")
        
        # All plots should now be in /tmp/ - upload them to Azure Storage
        plot_files = [
            ('/tmp/confusion_matrix.png', f'confusion_matrix_{timestamp}.png'),
            ('/tmp/roc_curve.png', f'roc_curve_{timestamp}.png'), 
            ('/tmp/pr_curve.png', f'pr_curve_{timestamp}.png'),
            ('/tmp/schedule_plot.png', f'schedule_plot_{timestamp}.png')
        ]
        
        uploaded_plots = 0
        for local_path, blob_name in plot_files:
            try:
                if os.path.exists(local_path):
                    file_size = os.path.getsize(local_path)
                    if file_size > 1000:  # Only upload if file has content
                        storage_helper.upload_file(local_path, "plots", blob_name)
                        logger.info(f"✅ Uploaded {blob_name} to Azure Storage ({file_size} bytes)")
                        uploaded_plots += 1
                    else:
                        logger.warning(f"⚠️ Plot file too small (may be empty): {local_path} ({file_size} bytes)")
                else:
                    logger.warning(f"⚠️ Plot file not found: {local_path}")
            except Exception as e:
                logger.error(f"❌ Failed to upload {blob_name}: {str(e)}")
        
        logger.info(f"📊 Uploaded {uploaded_plots}/{len(plot_files)} plots to Azure Storage")
        
        
        
        # 8) Send alerts
        logger.info("📧 Step 8: Sending alerts...")
        if os.getenv("EMAIL_ENABLED", "false").lower() == "true":
            send_email_alert(plan)
        else:
            logger.info("📧 Email alerts disabled")
            
        if os.getenv("SMS_ENABLED", "false").lower() == "true":
            send_sms_alert(plan)
        else:
            logger.info("📱 SMS alerts disabled")
        
        logger.info(f"✅ Pipeline completed! Generated plan with {len(plan)} interventions")
        logger.info(f"✅ Plan saved to Azure Storage: {plan_filename}")
        logger.info(f"✅ Plots uploaded to Azure Storage: {uploaded_plots} files")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Pipeline failed: {str(e)}")
        import traceback
        logger.error(f"🔍 Stack trace: {traceback.format_exc()}")
        return False

def scheduled_task():
    """Run the maintenance prediction on schedule"""
    logger.info("⏰ Running scheduled task...")
    run_maintenance_pipeline()

def start_scheduler():
    """Start the scheduled task runner"""
    schedule_time = os.getenv("SCHEDULE_TIME", "06:00")
    schedule.every().day.at(schedule_time).do(scheduled_task)
    
    logger.info(f"⏰ Scheduler started. Will run daily at {schedule_time}")
    
    # Run immediately on startup
    if os.getenv("RUN_ON_STARTUP", "true").lower() == "true":
        logger.info("🚀 Running initial prediction on startup...")
        threading.Thread(target=run_maintenance_pipeline).start()
    
    # Keep the scheduler running
    while True:
        schedule.run_pending()
        time.sleep(60)

if __name__ == "__main__":
    # Validate required environment variables
    required_vars = ["AZURE_STORAGE_CONNECTION_STRING"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {missing_vars}")
        exit(1)
    
    # Log configuration
    logger.info("🔧 Application Configuration:")
    logger.info(f"   Oracle: {os.getenv('ORACLE_HOST', 'Not set')}:{os.getenv('ORACLE_PORT', '1521')}")
    logger.info(f"   Schedule: {os.getenv('SCHEDULE_TIME', '06:00')}")
    logger.info(f"   Email Enabled: {os.getenv('EMAIL_ENABLED', 'false')}")
    logger.info(f"   Run on Startup: {os.getenv('RUN_ON_STARTUP', 'true')}")
    
    # Start scheduler
    scheduler_thread = threading.Thread(target=start_scheduler, daemon=True)
    scheduler_thread.start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")
