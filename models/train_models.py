import os
import sys

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import json
import time
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier, IsolationForest
from sklearn.metrics import classification_report, roc_auc_score, precision_recall_fscore_support
from config import Config

def generate_synthetic_kaggle_data(num_samples=25000, fraud_ratio=0.0017, random_state=42):
    """
    Generates a realistic synthetic dataset mirroring the Kaggle Credit Card Fraud dataset.
    Features: Time (0 to 172800 sec), V1..V28 (PCA components), Amount (USD/INR), Class (0 or 1).
    Fraud ratio: 0.17% matching Kaggle's 492 / 284,807.
    """
    np.random.seed(random_state)
    n_fraud = max(int(num_samples * fraud_ratio), 150) # Ensure sufficient fraud samples for training
    n_normal = num_samples - n_fraud

    # Normal transactions: V1-V28 centered around 0 with variance ~1.0
    normal_v = np.random.normal(0.0, 1.0, (n_normal, 28))
    normal_time = np.random.uniform(0, 172800, (n_normal, 1))
    # Normal amounts: log-normal distribution (majority under Rs. 5,000)
    normal_amount = np.random.lognormal(mean=3.5, sigma=1.2, size=(n_normal, 1))
    normal_class = np.zeros((n_normal, 1))

    # Fraud transactions: shifted distributions on key discriminant components
    # (In Kaggle literature, V1, V2, V3, V4, V10, V11, V12, V14, V17 show strong anomalies)
    fraud_v = np.random.normal(0.0, 1.5, (n_fraud, 28))
    fraud_v[:, 0] -= np.random.uniform(2.5, 6.0, n_fraud)   # V1
    fraud_v[:, 1] += np.random.uniform(2.0, 5.0, n_fraud)   # V2
    fraud_v[:, 2] -= np.random.uniform(3.0, 7.0, n_fraud)   # V3
    fraud_v[:, 3] += np.random.uniform(2.0, 6.0, n_fraud)   # V4
    fraud_v[:, 9] -= np.random.uniform(2.5, 6.0, n_fraud)   # V10
    fraud_v[:, 11] -= np.random.uniform(3.0, 7.5, n_fraud)  # V12
    fraud_v[:, 13] -= np.random.uniform(3.5, 8.0, n_fraud)  # V14
    fraud_v[:, 16] -= np.random.uniform(2.5, 6.5, n_fraud)  # V17

    t1 = np.random.uniform(3600, 14400, n_fraud // 2)  # Late night / odd hours
    t2 = np.random.uniform(72000, 86400, n_fraud - (n_fraud // 2))
    fraud_time = np.concatenate([t1, t2]).reshape(-1, 1)
    
    # Fraud amounts: typically either high bursts or test amounts
    n_high = int(n_fraud * 0.7)
    a1 = np.random.uniform(18000, 95000, n_high)
    a2 = np.random.uniform(1.0, 20.0, n_fraud - n_high)
    fraud_amount = np.concatenate([a1, a2]).reshape(-1, 1)
    fraud_class = np.ones((n_fraud, 1))

    # Combine
    normal_data = np.hstack([normal_time, normal_v, normal_amount, normal_class])
    fraud_data = np.hstack([fraud_time, fraud_v, fraud_amount, fraud_class])
    combined = np.vstack([normal_data, fraud_data])
    np.random.shuffle(combined)

    columns = ['Time'] + [f'V{i}' for i in range(1, 29)] + ['Amount', 'Class']
    df = pd.DataFrame(combined, columns=columns)
    return df

def train_and_save_models():
    """Trains Random Forest and Isolation Forest models and persists them to disk."""
    print("==================================================================")
    print("  CREDIT CARD FRAUD DETECTION - HYBRID ML MODEL TRAINER           ")
    print("  Supervised: Random Forest | Unsupervised: Isolation Forest       ")
    print("==================================================================")

    os.makedirs(Config.MODEL_DIR, exist_ok=True)
    kaggle_csv = os.path.join(Config.MODEL_DIR, 'creditcard.csv')

    if os.path.exists(kaggle_csv):
        print(f"[INFO] Found Kaggle dataset at: {kaggle_csv}")
        df = pd.read_csv(kaggle_csv)
    else:
        print("[INFO] Generating synthetic Kaggle dataset distribution...")
        df = generate_synthetic_kaggle_data(num_samples=25000)

    print(f"[DATA] Total samples: {len(df):,}, Frauds: {int(df['Class'].sum()):,} ({df['Class'].mean():.4%})")

    features = ['Time'] + [f'V{i}' for i in range(1, 29)] + ['Amount']
    X = df[features].copy()
    y = df['Class'].astype(int)

    # Preprocessing: Scale Time and Amount
    scaler = StandardScaler()
    X[['Time', 'Amount']] = scaler.fit_transform(X[['Time', 'Amount']])

    # Train / Test Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42, stratify=y
    )

    print(f"[DATA] Train set: {len(X_train):,}, Test set: {len(X_test):,}")

    # 1. Train Supervised Random Forest Classifier
    print("\n[TRAINING 1/2] Training Random Forest Classifier (Supervised)...")
    start_rf = time.time()
    rf_model = RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        class_weight='balanced',
        random_state=42,
        n_jobs=-1
    )
    rf_model.fit(X_train, y_train)
    rf_train_time = time.time() - start_rf
    print(f"[OK] Random Forest trained in {rf_train_time:.2f}s")

    # Evaluate RF
    rf_preds = rf_model.predict(X_test)
    rf_probs = rf_model.predict_proba(X_test)[:, 1]
    rf_roc_auc = roc_auc_score(y_test, rf_probs)
    p, r, f1, _ = precision_recall_fscore_support(y_test, rf_preds, average='binary')
    print(f"[EVAL] Random Forest - ROC AUC: {rf_roc_auc:.4f}, Precision: {p:.4f}, Recall: {r:.4f}, F1: {f1:.4f}")

    # 2. Train Unsupervised Isolation Forest Anomaly Detector
    # As per Slide 6: IsolationForest(n_estimators=100, contamination=0.0017, random_state=42)
    print("\n[TRAINING 2/2] Training Isolation Forest (Unsupervised Anomaly Detector)...")
    start_iso = time.time()
    iso_model = IsolationForest(
        n_estimators=100,
        contamination=0.0017,
        random_state=42,
        n_jobs=-1
    )
    # Isolation forest trains on normal behavior (unsupervised)
    iso_model.fit(X_train)
    iso_train_time = time.time() - start_iso
    print(f"[OK] Isolation Forest trained in {iso_train_time:.2f}s")

    # Evaluate Isolation Forest anomaly scoring on test set
    # -score_samples gives s(x, n) = 2^(-E[h(x)]/c(n))
    iso_raw = -iso_model.score_samples(X_test)
    # Anomaly scores near 0.5 or below are normal; near 0.72-1.0 are outliers
    iso_norm = np.clip((iso_raw - 0.45) / (0.75 - 0.45), 0.0, 1.0)
    iso_roc_auc = roc_auc_score(y_test, iso_norm)
    print(f"[EVAL] Isolation Forest - Anomaly ROC AUC: {iso_roc_auc:.4f}")

    # 3. Hybrid Score Evaluation
    hybrid_scores = 0.7 * (rf_probs * 100) + 0.3 * (iso_norm * 100)
    hybrid_preds = (hybrid_scores >= 40).astype(int)
    hybrid_auc = roc_auc_score(y_test, hybrid_scores / 100.0)
    print(f"[EVAL] Hybrid Risk Score - ROC AUC: {hybrid_auc:.4f}")

    # Save artifacts
    print("\n[SAVING] Persisting models to disk...")
    joblib.dump(rf_model, Config.RF_MODEL_PATH)
    joblib.dump(iso_model, Config.ISO_MODEL_PATH)
    joblib.dump(scaler, Config.SCALER_PATH)

    metrics = {
        'training_timestamp': time.strftime("%Y-%m-%d %H:%M:%S"),
        'total_samples': len(df),
        'rf_metrics': {
            'roc_auc': round(float(rf_roc_auc), 4),
            'precision': round(float(p), 4),
            'recall': round(float(r), 4),
            'f1_score': round(float(f1), 4),
            'training_time_sec': round(rf_train_time, 2)
        },
        'iso_metrics': {
            'roc_auc': round(float(iso_roc_auc), 4),
            'n_estimators': 100,
            'contamination': 0.0017,
            'training_time_sec': round(iso_train_time, 2)
        },
        'hybrid_metrics': {
            'roc_auc': round(float(hybrid_auc), 4),
            'formula': '0.7 * (RF_Prob * 100) + 0.3 * (ISO_Score * 100)'
        }
    }

    metrics_path = os.path.join(Config.MODEL_DIR, 'model_metrics.json')
    with open(metrics_path, 'w') as f:
        json.dump(metrics, f, indent=4)

    print(f"[SUCCESS] Models and metrics saved successfully to {Config.MODEL_DIR}")
    return metrics

if __name__ == '__main__':
    train_and_save_models()
