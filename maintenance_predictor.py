# maintenance_predictor.py
import os
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# === Core libs ===
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for containers
import matplotlib.pyplot as plt

# === ML ===
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    classification_report,
    roc_auc_score,
    confusion_matrix,
    precision_recall_curve,
    roc_curve
)

import xgboost as xgb

# === Oracle / Email / SMS ===
import oracledb
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Optional SMS
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except Exception:
    TWILIO_AVAILABLE = False

# Optional .env support
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ========== CONFIGURATION ==========
# Oracle connection - from environment variables
ORACLE_USER = os.getenv("ORACLE_USER", "system")
ORACLE_PASS = os.getenv("ORACLE_PASS", "Oracle123")
ORACLE_HOST = os.getenv("ORACLE_HOST", "localhost")
ORACLE_PORT = os.getenv("ORACLE_PORT", "1521")
ORACLE_SERVICE = os.getenv("ORACLE_SERVICE", "XE")

# Date window
EXTRACT_START = os.getenv("EXTRACT_START", "2025-01-01")
EXTRACT_END   = datetime.now().strftime("%Y-%m-%d")

# Exclusions
EXCLUSION_KEYWORDS = [
    "voiture", "voiuture", "batiments", "bâtiments", "villa",
    "camionette", "camionnette", "mazda", "siège", "siege", "volvo"
]

# Planning
PLANNING_HORIZON_DAYS = int(os.getenv("PLANNING_HORIZON_DAYS", "90"))
NUM_FUTURE_DATES = int(os.getenv("NUM_FUTURE_DATES", "3"))

# Email alert config
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
EMAIL_SMTP = os.getenv("EMAIL_SMTP", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USER = os.getenv("EMAIL_USER", "mohameddhia.abidi02@gmail.com")
EMAIL_PASS = os.getenv("EMAIL_PASS", "viob slun xjgi tzgn")
EMAIL_TO   = os.getenv("EMAIL_TO",   EMAIL_USER)

# SMS alert config (optional)
SMS_ENABLED = (os.getenv("SMS_ENABLED", "false").lower() == "true") and TWILIO_AVAILABLE
TWILIO_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_TOKEN= os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
SMS_TO      = os.getenv("SMS_TO", "")

# Random seed
RANDOM_STATE = 42

# === 0. Oracle Extract ===
def extract_from_oracle(start_date: str, end_date: str) -> pd.DataFrame:
    print("Connecting to Oracle and extracting data...")
    
    # Use thin mode - no Oracle client required in container
    dsn = f"{ORACLE_HOST}:{ORACLE_PORT}/{ORACLE_SERVICE}"
    
    sql = """
    SELECT
        SUM(t.ot_depse_moi + t.ot_depse_moe + t.ot_depse_pres + t.ot_depse_piece) AS total_depense,
        t.OT_DATEDEB,
        t.OT_DATEFIN,
        t.OT_DATEDEM,
        t.OT_CODE,
        t.ART_CODE,
        t.OT_PREVU,
        a.ART_LIB,
        t.OT_REAL
    FROM
        ordre_travail t
    JOIN
        article a ON t.art_code = a.art_code
    WHERE
        t.OT_DATEDEM BETWEEN TO_DATE(:date_deb, 'YYYY-MM-DD') AND TO_DATE(:date_fin, 'YYYY-MM-DD')
    GROUP BY
        t.OT_DATEDEB, t.OT_DATEFIN, t.OT_DATEDEM,
        t.OT_CODE, t.ART_CODE, t.OT_PREVU, a.ART_LIB, t.OT_REAL
    """
    
    try:
        # Use thin mode connection
        with oracledb.connect(user=ORACLE_USER, password=ORACLE_PASS, dsn=dsn) as conn:
            df = pd.read_sql(sql, con=conn, params={"date_deb": start_date, "date_fin": end_date})
        print(f"✅ Successfully extracted {len(df)} records from Oracle")
        return df
    except Exception as e:
        print(f"❌ Oracle extraction failed: {str(e)}")
        raise

# === 1. Preprocess ===
def preprocess(df: pd.DataFrame) -> pd.DataFrame:
    print("Preprocessing data...")
    cols = ['TOTAL_DEPENSE', 'OT_DATEDEB', 'OT_DATEFIN', 'OT_DATEDEM',
            'OT_CODE', 'ART_CODE', 'OT_PREVU', 'ART_LIB', 'OT_REAL']
    df = df[cols].copy()

    # Dates
    for c in ['OT_DATEDEB', 'OT_DATEFIN', 'OT_DATEDEM']:
        df[c] = pd.to_datetime(df[c], errors='coerce')

    # Exclusions
    mask = df['ART_LIB'].str.lower().str.contains('|'.join(EXCLUSION_KEYWORDS), na=False)
    df = df[~mask].copy()

    # Sort
    df = df.sort_values(['ART_CODE', 'OT_DATEDEM'])
    return df

# === 2. Feature Engineering ===
def build_features(df: pd.DataFrame) -> pd.DataFrame:
    print("Creating features...")

    # Durations & intervals
    df['DURATION_DAYS'] = (df['OT_DATEFIN'] - df['OT_DATEDEB']).dt.days
    df['DURATION_DAYS'] = df['DURATION_DAYS'].fillna(0).clip(lower=0)

    df['PREV_DATE'] = df.groupby('ART_CODE')['OT_DATEDEM'].shift(1)
    df['DAYS_SINCE_LAST'] = (df['OT_DATEDEM'] - df['PREV_DATE']).dt.days
    df['DAYS_SINCE_LAST'] = df['DAYS_SINCE_LAST'].fillna(0).clip(lower=0)

    # Preventive detection from text
    preventive_keywords = ['entretien', 'nettoyage', 'lubrification', 'inspection', 'preventive', 'préventif', 'preventif']
    df['IS_PREVENTIVE'] = df['OT_PREVU'].str.lower().str.contains('|'.join(preventive_keywords), na=False).astype(int)

    # Frequencies / Rolling
    df['INTERVENTION_COUNT'] = df.groupby('ART_CODE').cumcount() + 1
    df['AVG_INTERVAL'] = df.groupby('ART_CODE')['DAYS_SINCE_LAST'].transform(lambda s: s.expanding().mean()).fillna(0)

    # Rolling average cost (3)
    df['ROLLING_AVG_COST'] = df.groupby('ART_CODE')['TOTAL_DEPENSE'].transform(lambda s: s.rolling(3, min_periods=1).mean()).fillna(0)

    # Seasonality & calendar
    df['YEAR'] = df['OT_DATEDEM'].dt.year
    df['MONTH'] = df['OT_DATEDEM'].dt.month
    df['DAYOFWEEK'] = df['OT_DATEDEM'].dt.dayofweek
    df['WEEKOFYEAR'] = df['OT_DATEDEM'].dt.isocalendar().week.astype(int)
    df['QUARTER'] = df['OT_DATEDEM'].dt.quarter

    # Targets
    today = pd.to_datetime('today').normalize()
    df['DAYS_SINCE_LAST_INTERV'] = (today - df.groupby('ART_CODE')['OT_DATEDEM'].transform('max')).dt.days.fillna(365)

    df['NEXT_INTERVENTION'] = df.groupby('ART_CODE')['OT_DATEDEM'].shift(-1)
    df['TARGET'] = ((df['NEXT_INTERVENTION'] - df['OT_DATEDEM']).dt.days <= 30).astype(int).fillna(0)

    # Equipment failure ratio (historical)
    df['EQUIP_FAIL_RATIO'] = df.groupby('ART_CODE')['TARGET'].transform(lambda s: s.rolling(len(s), min_periods=1).mean()).fillna(0)

    # Interval target (next interval)
    df['INTERVAL_TARGET'] = df.groupby('ART_CODE')['DAYS_SINCE_LAST'].shift(-1)
    df['INTERVAL_TARGET'] = df['INTERVAL_TARGET'].fillna(df['AVG_INTERVAL']).clip(lower=7, upper=365)

    return df

# === 3. Train XGBoost Models ===
def train_models(df: pd.DataFrame):
    print("Training XGBoost models (Classifier + Regressor)...")

    feature_cols = [
        'DAYS_SINCE_LAST_INTERV', 'AVG_INTERVAL', 'IS_PREVENTIVE',
        'ROLLING_AVG_COST', 'DURATION_DAYS', 'TOTAL_DEPENSE',
        'MONTH', 'DAYOFWEEK', 'WEEKOFYEAR', 'QUARTER', 'EQUIP_FAIL_RATIO'
    ]

    # Classification
    X = df[feature_cols].fillna(0)
    y_clf = df['TARGET'].astype(int)

    # Regression
    y_reg = df['INTERVAL_TARGET'].astype(float)

    # Splits
    X_train_c, X_test_c, y_train_c, y_test_c = train_test_split(
        X, y_clf, test_size=0.3, random_state=RANDOM_STATE, stratify=y_clf
    )
    X_train_r, X_test_r, y_train_r, y_test_r = train_test_split(
        X, y_reg, test_size=0.3, random_state=RANDOM_STATE
    )

    # Class imbalance handling
    neg, pos = (y_train_c == 0).sum(), (y_train_c == 1).sum()
    scale_pos = max(1.0, neg / max(1, pos))

    # Classifier
    clf = xgb.XGBClassifier(
        n_estimators=600,
        max_depth=6,
        learning_rate=0.05,
        subsample=0.85,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        scale_pos_weight=scale_pos,
        random_state=RANDOM_STATE,
        n_jobs=-1,
        eval_metric='logloss'
    )
    clf.fit(X_train_c, y_train_c)

    # Regressor
    reg = xgb.XGBRegressor(
        n_estimators=700,
        max_depth=5,
        learning_rate=0.05,
        subsample=0.9,
        colsample_bytree=0.85,
        reg_lambda=1.0,
        random_state=RANDOM_STATE,
        n_jobs=-1
    )
    reg.fit(X_train_r, y_train_r)

    # === Evaluation ===
    print("\n=== Classification Report ===")
    y_pred_c = clf.predict(X_test_c)
    print(classification_report(y_test_c, y_pred_c))

    # ROC-AUC
    y_prob_c = clf.predict_proba(X_test_c)[:, 1]
    try:
        roc_auc = roc_auc_score(y_test_c, y_prob_c)
        print(f"ROC-AUC: {roc_auc:.3f}")
    except Exception:
        pass

    # Confusion Matrix plot
    plot_confusion_matrix(y_test_c, y_pred_c, title="Confusion Matrix (XGB Classifier)")

    # ROC and PR plots
    plot_roc_curve(y_test_c, y_prob_c, title="ROC Curve (XGB Classifier)")
    plot_pr_curve(y_test_c, y_prob_c, title="Precision-Recall (XGB Classifier)")

    return clf, reg, feature_cols

def plot_confusion_matrix(y_true, y_pred, title="Confusion Matrix"):
    cm = confusion_matrix(y_true, y_pred)
    plt.figure(figsize=(5, 4))
    plt.imshow(cm, interpolation='nearest')
    plt.title(title)
    plt.colorbar()
    tick_marks = np.arange(2)
    plt.xticks(tick_marks, ['0', '1'])
    plt.yticks(tick_marks, ['0', '1'])
    thresh = cm.max() / 2.
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            plt.text(j, i, format(cm[i, j], 'd'),
                     ha="center", va="center",
                     color="white" if cm[i, j] > thresh else "black")
    plt.ylabel('True label')
    plt.xlabel('Predicted label')
    plt.tight_layout()
    # REPLACE plt.show() with plt.savefig()
    plt.savefig('/tmp/confusion_matrix.png', dpi=300, bbox_inches='tight')
    plt.close()  # Important: close the figure
    print("✅ Confusion matrix plot saved")


def plot_roc_curve(y_true, y_prob, title="ROC Curve"):
    fpr, tpr, _ = roc_curve(y_true, y_prob)
    auc_val = roc_auc_score(y_true, y_prob)
    plt.figure(figsize=(5, 4))
    plt.plot(fpr, tpr, label=f"AUC = {auc_val:.3f}")
    plt.plot([0, 1], [0, 1], 'k--')
    plt.xlabel('False Positive Rate')
    plt.ylabel('True Positive Rate')
    plt.title(title)
    plt.legend(loc='lower right')
    plt.tight_layout()
    # REPLACE plt.show() with plt.savefig()
    plt.savefig('/tmp/roc_curve.png', dpi=300, bbox_inches='tight')
    plt.close()  # Important: close the figure
    print("✅ ROC curve plot saved")


def plot_pr_curve(y_true, y_prob, title="Precision-Recall Curve"):
    precision, recall, _ = precision_recall_curve(y_true, y_prob)
    plt.figure(figsize=(5, 4))
    plt.plot(recall, precision)
    plt.xlabel('Recall')
    plt.ylabel('Precision')
    plt.title(title)
    plt.tight_layout()
    # REPLACE plt.show() with plt.savefig()
    plt.savefig('/tmp/pr_curve.png', dpi=300, bbox_inches='tight')
    plt.close()  # Important: close the figure
    print("✅ Precision-Recall curve plot saved")

# === 4. Planning ===
def generate_planning(df: pd.DataFrame, clf, reg, features: list[str],
                      horizon_days: int = PLANNING_HORIZON_DAYS,
                      num_future: int = NUM_FUTURE_DATES) -> pd.DataFrame:
    print("Generating planning...")
    today = pd.to_datetime('today').normalize()
    horizon_date = today + timedelta(days=horizon_days)

    # Latest state per equipment
    latest = df.sort_values(['ART_CODE', 'OT_DATEDEM']).groupby('ART_CODE').tail(1).copy()

    # Predictions
    X_curr = latest[features].fillna(0)
    latest['FAILURE_PROBABILITY'] = clf.predict_proba(X_curr)[:, 1]
    pred_interval = reg.predict(X_curr)
    # lower-bound only: at least 7 days, no artificial cap
    latest['PREDICTED_INTERVAL'] = np.maximum(pred_interval, 7.0)

    latest['LAST_MAINT_DATE'] = latest['OT_DATEDEM']

    # Multi-future dates
    for i in range(1, num_future + 1):
        latest[f'NEXT_MAINT_DATE_{i}'] = latest['LAST_MAINT_DATE'] + pd.to_timedelta(latest['PREDICTED_INTERVAL'] * i, unit='D')

    # Choose the next date within horizon (or earliest future)
    def pick_next_date(row):
        dates = [row[f'NEXT_MAINT_DATE_{i}'] for i in range(1, num_future + 1)]
        in_window = [d for d in dates if pd.notna(d) and today <= d <= horizon_date]
        if in_window:
            return min(in_window)
        future = [d for d in dates if pd.notna(d) and d >= today]
        return min(future) if future else np.nan

    latest['NEXT_MAINT_DATE'] = latest.apply(pick_next_date, axis=1)

    # Filter to planned window or nearest future
    plan = latest[latest['NEXT_MAINT_DATE'].notna()].copy()

    # Priority scoring
    plan['DAYS_UNTIL_NEXT'] = (plan['NEXT_MAINT_DATE'] - today).dt.days
    plan['PRIORITY_SCORE'] = (
        0.6 * plan['FAILURE_PROBABILITY'] +
        0.4 * (1 - (plan['DAYS_UNTIL_NEXT'] / horizon_days)).clip(0, 1)
    )

    plan['PRIORITY'] = pd.cut(
        plan['PRIORITY_SCORE'],
        bins=[-1, 0.4, 0.6, 0.8, 1.1],
        labels=['Low', 'Medium', 'High', 'Critical']
    )

    cols = [
        'ART_CODE', 'ART_LIB', 'FAILURE_PROBABILITY', 'PRIORITY', 'PRIORITY_SCORE',
        'LAST_MAINT_DATE', 'PREDICTED_INTERVAL', 'NEXT_MAINT_DATE'
    ] + [f'NEXT_MAINT_DATE_{i}' for i in range(1, num_future + 1)]

    plan = plan[cols].sort_values(['PRIORITY', 'NEXT_MAINT_DATE', 'PRIORITY_SCORE'], ascending=[False, True, False])
    return plan

# === 5. Visualization (bubble schedule) ===
def plot_schedule(plan_df: pd.DataFrame, horizon_days: int = PLANNING_HORIZON_DAYS):
    if plan_df.empty:
        print("No planned interventions to plot within horizon.")
        return
    plt.figure(figsize=(14, 8))
    colors = {'Critical': 'red', 'High': 'orange', 'Medium': 'blue', 'Low': 'green'}
    for priority, group in plan_df.groupby('PRIORITY'):
        plt.scatter(
            group['NEXT_MAINT_DATE'], group['ART_CODE'],
            s=group['FAILURE_PROBABILITY'] * 250 + 40,
            c=colors.get(priority, 'gray'),
            alpha=0.7, label=f'{priority}'
        )
    plt.axvline(pd.to_datetime('today').normalize(), color='black', linestyle='--', label='Today')
    plt.title(f'Maintenance Schedule (Next {horizon_days} Days)\nBubble = Failure Probability', pad=20)
    plt.xlabel('Scheduled Date')
    plt.ylabel('Equipment (ART_CODE)')
    plt.legend(bbox_to_anchor=(1.02, 1), loc='upper left')
    plt.grid(alpha=0.3)
    plt.xticks(rotation=45)
    plt.tight_layout()
    # REPLACE plt.show() with plt.savefig()
    plt.savefig('/tmp/schedule_plot.png', dpi=300, bbox_inches='tight')
    plt.close()  # Important: close the figure
    print("✅ Schedule plot saved to /tmp/schedule_plot.png")

# === 6. Alerts ===
def send_email_alert(plan_df: pd.DataFrame):
    if not EMAIL_ENABLED:
        print("Email alerts disabled.")
        return
    if plan_df.empty or 'NEXT_MAINT_DATE' not in plan_df:
        print("No interventions scheduled (email).")
        return
    today = pd.to_datetime('today').normalize()
    due_today = plan_df[plan_df['NEXT_MAINT_DATE'].dt.normalize() == today]
    if due_today.empty:
        print("No interventions scheduled for today (email).")
        return

    subject = f"[ALERT] {len(due_today)} Preventive Interventions Due Today ({today.date()})"
    body = "The following interventions are due today:\n\n"
    body += due_today[['ART_CODE', 'ART_LIB', 'PRIORITY', 'NEXT_MAINT_DATE']].to_string(index=False)

    msg = MIMEMultipart()
    msg['From'] = EMAIL_USER
    msg['To'] = EMAIL_TO
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(EMAIL_SMTP, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASS)
        server.sendmail(msg['From'], msg['To'], msg.as_string())
        server.quit()
        print("✅ Email alert sent successfully!")
    except Exception as e:
        print("❌ Failed to send email:", str(e))

def send_sms_alert(plan_df: pd.DataFrame):
    if not (SMS_ENABLED and TWILIO_AVAILABLE):
        print("SMS alerts disabled or Twilio not available.")
        return
    if plan_df.empty or 'NEXT_MAINT_DATE' not in plan_df:
        print("No interventions scheduled (SMS).")
        return
    today = pd.to_datetime('today').normalize()
    due_today = plan_df[plan_df['NEXT_MAINT_DATE'].dt.normalize() == today]
    if due_today.empty:
        print("No interventions scheduled for today (SMS).")
        return

    text = f"⚠️ {len(due_today)} interventions due today:\n"
    for _, r in due_today.iterrows():
        text += f"- {r['ART_CODE']} | {r['PRIORITY']} | {r['NEXT_MAINT_DATE'].date()}\n"

    try:
        client = TwilioClient(TWILIO_SID, TWILIO_TOKEN)
        msg = client.messages.create(body=text, from_=TWILIO_FROM, to=SMS_TO)
        print("✅ SMS alert sent:", msg.sid)
    except Exception as e:
        print("❌ Failed to send SMS:", str(e))
