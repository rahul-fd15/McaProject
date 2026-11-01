import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'bank_fraud_detection_secret_key_2026_mca')
    
    # Database configuration
    # Default is SQLite for zero-setup execution. Can be switched to MySQL:
    # "mysql+mysqlconnector://user:password@localhost/dummy_bank"
    DB_ENGINE = os.environ.get('DB_ENGINE', 'sqlite')
    SQLITE_DB_PATH = os.path.join(BASE_DIR, 'data', 'dummy_bank.db')
    
    # Model configuration
    MODEL_DIR = os.path.join(BASE_DIR, 'data')
    RF_MODEL_PATH = os.path.join(MODEL_DIR, 'rf_model.pkl')
    ISO_MODEL_PATH = os.path.join(MODEL_DIR, 'iso_model.pkl')
    SCALER_PATH = os.path.join(MODEL_DIR, 'scaler.pkl')
    
    # Hybrid ML Scoring weights (From Abstract slide 5)
    RF_WEIGHT = 0.7
    ISO_WEIGHT = 0.3
    
    # Risk Decision Thresholds
    RISK_APPROVE_MAX = 39    # 0 - 39: Approve
    RISK_FLAG_MAX = 69       # 40 - 69: Flag & send SMS alert
    RISK_BLOCK_MIN = 70      # 70 and above: Block card & send SMS
    
    # Security Rules
    MAX_FAILED_PIN_ATTEMPTS = 3
    
    # SMS Gateway Configuration
    # Modes: 'MOCK' (instant local simulation with audit trail) or 'TWILIO' or 'FAST2SMS'
    SMS_GATEWAY_MODE = os.environ.get('SMS_GATEWAY_MODE', 'MOCK')
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')
    FAST2SMS_API_KEY = os.environ.get('FAST2SMS_API_KEY', '')
