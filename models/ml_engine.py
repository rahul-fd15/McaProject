import os
import sys
import numpy as np
import pandas as pd
import joblib

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from models.train_models import train_and_save_models

class FraudDetectionEngine:
    _instance = None

    def __init__(self):
        self.rf_model = None
        self.iso_model = None
        self.scaler = None
        self.feature_names = ['Time'] + [f'V{i}' for i in range(1, 29)] + ['Amount']
        self.load_or_train_models()

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = FraudDetectionEngine()
        return cls._instance

    def load_or_train_models(self):
        """Loads serialized models from disk, or trains them if not found."""
        if not (os.path.exists(Config.RF_MODEL_PATH) and 
                os.path.exists(Config.ISO_MODEL_PATH) and 
                os.path.exists(Config.SCALER_PATH)):
            print("[ML Engine] Model files not found. Initiating model training...")
            train_and_save_models()

        self.rf_model = joblib.load(Config.RF_MODEL_PATH)
        self.iso_model = joblib.load(Config.ISO_MODEL_PATH)
        self.scaler = joblib.load(Config.SCALER_PATH)
        print("[ML Engine] Random Forest & Isolation Forest successfully loaded into memory.")

    def construct_features(self, amount, merchant, location, card_limit=100000.0, custom_v=None, hour=None):
        """
        Constructs the 30 Kaggle-aligned features [Time, V1..V28, Amount].
        Maps banking attributes (merchant, location risk, amount ratio, hour) into Kaggle PCA space.
        """
        # 1. Time (seconds from midnight or transaction hour)
        if hour is None:
            now_dt = pd.Timestamp.now()
            seconds_in_day = now_dt.hour * 3600 + now_dt.minute * 60 + now_dt.second
        else:
            seconds_in_day = int(hour) * 3600

        # If custom vector is explicitly supplied (e.g. from Kaggle dataset test row)
        if custom_v is not None and len(custom_v) == 28:
            v_vector = np.array(custom_v, dtype=float)
        else:
            # Domain-driven PCA mapping matching real-world credit card fraud characteristics:
            # High risk merchants: Crypto, Casino, Overseas Wire, Unknown Online Gateways
            merchant_lower = str(merchant).lower()
            location_lower = str(location).lower()

            high_risk_merchants = ['crypto', 'bitcoin', 'binance', 'casino', 'betting', 'wire transfer', 'darkweb', 'luxury jewelry']
            medium_risk_merchants = ['apple store', 'electronics', 'gift cards', 'steam games', 'online store', 'foreign currency']

            is_high_risk_merchant = any(k in merchant_lower for k in high_risk_merchants)
            is_med_risk_merchant = any(k in merchant_lower for k in medium_risk_merchants)

            # Location risk
            is_intl = any(k in location_lower for k in ['international', 'overseas', 'nigeria', 'russia', 'cayman', 'panama', 'dubai', 'unknown ip'])

            # Amount ratio relative to limit
            amt_float = float(amount)
            limit_ratio = amt_float / max(float(card_limit), 1000.0)

            # Night hours (1 AM to 5 AM)
            current_hour = (seconds_in_day // 3600) % 24
            is_odd_hour = 1 <= current_hour <= 5

            # Calculate risk perturbation index (0.0 to 1.0)
            risk_factor = 0.0
            if is_high_risk_merchant:
                risk_factor += 0.60
            elif is_med_risk_merchant:
                risk_factor += 0.25

            if is_intl:
                risk_factor += 0.25

            if limit_ratio > 0.65:
                risk_factor += 0.45
            elif limit_ratio > 0.30:
                risk_factor += 0.20

            if is_odd_hour and amt_float > 5000:
                risk_factor += 0.15

            # Base normal V components (near 0)
            np.random.seed(int(amt_float * 100) % 10000)
            v_vector = np.random.normal(0.0, 0.4, 28)

            # Apply PCA shifts proportional to risk_factor
            if risk_factor >= 0.75:
                # Strong fraud signature on primary Kaggle components
                v_vector[0] -= np.random.uniform(3.5, 6.0)   # V1
                v_vector[1] += np.random.uniform(3.0, 5.5)   # V2
                v_vector[2] -= np.random.uniform(4.0, 7.0)   # V3
                v_vector[3] += np.random.uniform(3.0, 6.0)   # V4
                v_vector[9] -= np.random.uniform(3.0, 6.0)   # V10
                v_vector[11] -= np.random.uniform(3.5, 7.5)  # V12
                v_vector[13] -= np.random.uniform(4.0, 8.0)  # V14
                v_vector[16] -= np.random.uniform(3.0, 6.5)  # V17
            elif risk_factor >= 0.35:
                # Moderate anomaly / suspicious pattern
                v_vector[0] -= np.random.uniform(2.2, 3.2)
                v_vector[1] += np.random.uniform(1.8, 2.8)
                v_vector[2] -= np.random.uniform(2.5, 3.8)
                v_vector[3] += np.random.uniform(1.8, 2.8)
                v_vector[9] -= np.random.uniform(1.8, 2.8)
                v_vector[13] -= np.random.uniform(2.2, 3.5)
                v_vector[16] -= np.random.uniform(1.8, 3.0)

        # Assemble full vector: [Time, V1..V28, Amount]
        raw_features = np.zeros(30)
        raw_features[0] = seconds_in_day
        raw_features[1:29] = v_vector
        raw_features[29] = float(amount)

        return raw_features

    def evaluate_risk(self, amount, merchant, location, card_limit=100000.0, custom_v=None, hour=None):
        """
        Runs the Hybrid ML Fraud Detection pipeline:
        1. Preprocesses features with StandardScaler.
        2. Supervised: Random Forest -> rf_prob.
        3. Unsupervised: Isolation Forest -> iso_score.
        4. Combines: 0.7 * (rf_prob * 100) + 0.3 * (iso_score * 100).
        5. Returns Risk Score (0-100), decision, and rule explanation.
        """
        raw_features = self.construct_features(
            amount=amount,
            merchant=merchant,
            location=location,
            card_limit=card_limit,
            custom_v=custom_v,
            hour=hour
        )

        # Preprocess features: Scale Time and Amount
        feat_df = pd.DataFrame([raw_features], columns=self.feature_names)
        scaled_df = feat_df.copy()
        scaled_df[['Time', 'Amount']] = self.scaler.transform(feat_df[['Time', 'Amount']])

        # 1. Random Forest (Supervised) -> fraud probability
        rf_prob = float(self.rf_model.predict_proba(scaled_df)[0][1])

        # 2. Isolation Forest (Unsupervised) -> anomaly score
        # s(x, n) = 2^(-E[h(x)]/c(n))
        iso_raw = float(-self.iso_model.score_samples(scaled_df)[0])
        # Normalized anomaly score from 0.0 to 1.0 (0.45 = normal inlier, 0.75+ = outlier)
        iso_score = float(np.clip((iso_raw - 0.45) / (0.75 - 0.45), 0.0, 1.0))

        # 3. Blended Hybrid Risk Score (0 - 100)
        # Risk score (0–100) = 0.7 * RF fraud probability * 100 + 0.3 * Isolation Forest anomaly score * 100
        risk_score_float = (Config.RF_WEIGHT * (rf_prob * 100.0)) + (Config.ISO_WEIGHT * (iso_score * 100.0))
        risk_score = int(np.clip(round(risk_score_float), 0, 100))

        # 4. Threshold & Decision Logic (From Slide 5)
        # 0 – 39: Approve
        # 40 – 69: Flag & send SMS alert
        # 70 and above: Block card & send SMS
        if risk_score >= Config.RISK_BLOCK_MIN:
            decision = 'BLOCKED'
            if float(amount) > float(card_limit) * 0.7:
                rule_hit = f'Extreme Amount Spike (Rs. {amount:,.2f}) & Novel Anomaly (Risk {risk_score})'
            elif any(k in str(merchant).lower() for k in ['crypto', 'casino', 'wire']):
                rule_hit = f'High-Risk Merchant & Anomaly Vector (Risk {risk_score})'
            elif any(k in str(location).lower() for k in ['international', 'overseas', 'unknown ip']):
                rule_hit = f'High-Risk Geo-Location & Cluster Deviation (Risk {risk_score})'
            else:
                rule_hit = f'Critical Fraud Threat Hit: RF Prob {rf_prob*100:.1f}%, ISO Score {iso_score*100:.1f}%'
        elif risk_score >= 40:
            decision = 'FLAGGED'
            rule_hit = f'Suspicious Pattern: Risk {risk_score} (RF: {rf_prob*100:.1f}%, ISO: {iso_score*100:.1f}%)'
        else:
            decision = 'APPROVED'
            rule_hit = f'Normal Transaction Pattern (Risk Score: {risk_score})'

        return {
            'risk_score': risk_score,
            'rf_prob': round(rf_prob, 4),
            'iso_score': round(iso_score, 4),
            'decision': decision,
            'rule_hit': rule_hit,
            'raw_features': raw_features.tolist()
        }

# Global singleton
ml_engine = FraudDetectionEngine.get_instance()
