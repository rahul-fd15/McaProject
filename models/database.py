import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from config import Config

def get_db_connection():
    """Returns a connection to the SQLite database with dictionary-like row access."""
    conn = sqlite3.connect(Config.SQLITE_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    """Initializes the database schema matching the 7 tables from Project Slides 9 & 10."""
    os.makedirs(os.path.dirname(Config.SQLITE_DB_PATH), exist_ok=True)
    conn = get_db_connection()
    cursor = conn.cursor()

    # D1: CUSTOMER Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CUSTOMER (
        customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name VARCHAR(50) NOT NULL,
        email VARCHAR(60) UNIQUE NOT NULL,
        phone VARCHAR(15) NOT NULL,
        address VARCHAR(100),
        password_hash VARCHAR(255) NOT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # D2: CARD Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CARD (
        card_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        card_number VARCHAR(16) UNIQUE NOT NULL,
        card_type VARCHAR(15) DEFAULT 'Visa',
        credit_limit DECIMAL(12, 2) NOT NULL DEFAULT 100000.00,
        available_limit DECIMAL(12, 2) NOT NULL DEFAULT 100000.00,
        expiry_date DATE NOT NULL,
        pin_hash VARCHAR(255) NOT NULL,
        failed_pin_attempts INTEGER DEFAULT 0,
        status VARCHAR(10) DEFAULT 'ACTIVE',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES CUSTOMER(customer_id) ON DELETE CASCADE
    );
    """)

    # D3: TRANSACTION Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS `TRANSACTION` (
        txn_id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_id INTEGER NOT NULL,
        amount DECIMAL(12, 2) NOT NULL,
        txn_time DATETIME NOT NULL,
        merchant VARCHAR(50) NOT NULL,
        location VARCHAR(30) NOT NULL,
        status VARCHAR(15) NOT NULL,
        FOREIGN KEY (card_id) REFERENCES CARD(card_id) ON DELETE CASCADE
    );
    """)

    # D4: FRAUD_ALERT Table (Includes rf_prob & iso_score from Slide 10)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS FRAUD_ALERT (
        alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
        txn_id INTEGER NOT NULL,
        rule_hit VARCHAR(50) NOT NULL,
        risk_score INTEGER NOT NULL,
        rf_prob DECIMAL(6, 4) NOT NULL,
        iso_score DECIMAL(6, 4) NOT NULL,
        alert_status VARCHAR(15) DEFAULT 'NEW',
        alert_time DATETIME NOT NULL,
        FOREIGN KEY (txn_id) REFERENCES `TRANSACTION`(txn_id) ON DELETE CASCADE
    );
    """)

    # D5: ADMIN Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ADMIN (
        admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username VARCHAR(30) UNIQUE NOT NULL,
        password_hash VARCHAR(255) NOT NULL,
        role VARCHAR(20) DEFAULT 'SUPER_ADMIN'
    );
    """)

    # D6: SMS_LOG Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS SMS_LOG (
        sms_id INTEGER PRIMARY KEY AUTOINCREMENT,
        alert_id INTEGER,
        phone VARCHAR(15) NOT NULL,
        message VARCHAR(160) NOT NULL,
        sms_status VARCHAR(15) NOT NULL,
        sent_time DATETIME NOT NULL,
        FOREIGN KEY (alert_id) REFERENCES FRAUD_ALERT(alert_id) ON DELETE SET NULL
    );
    """)

    # D7: CHAT_LOG Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CHAT_LOG (
        chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        user_message VARCHAR(200) NOT NULL,
        intent VARCHAR(30) NOT NULL,
        bot_reply VARCHAR(255) NOT NULL,
        chat_time DATETIME NOT NULL,
        FOREIGN KEY (customer_id) REFERENCES CUSTOMER(customer_id) ON DELETE CASCADE
    );
    """)

    conn.commit()
    conn.close()

def mask_card_number(card_number):
    """Utility to mask card number e.g. '4111222233334821' -> 'XXXX XXXX XXXX 4821' or 'XX4821'"""
    clean = str(card_number).replace(" ", "").replace("-", "")
    if len(clean) >= 4:
        return f"•••• •••• •••• {clean[-4:]}"
    return "••••"

def short_mask(card_number):
    """Short mask for SMS messages e.g. 'XX4821'"""
    clean = str(card_number).replace(" ", "").replace("-", "")
    if len(clean) >= 4:
        return f"XX{clean[-4:]}"
    return "XX****"
