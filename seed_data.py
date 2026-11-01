import os
import sys
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from models.database import init_db, get_db_connection

def seed_database():
    print("[SEED] Initializing database schema...")
    init_db()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Clear existing data for fresh seed
    for table in ['CHAT_LOG', 'SMS_LOG', 'FRAUD_ALERT', '`TRANSACTION`', 'CARD', 'CUSTOMER', 'ADMIN']:
        cursor.execute(f"DELETE FROM {table}")
    try:
        cursor.execute("DELETE FROM sqlite_sequence")
    except Exception:
        pass

    print("[SEED] Creating Bank Admins...")
    admin_pw = generate_password_hash("admin123")
    cursor.execute("""
        INSERT INTO ADMIN (username, password_hash, role)
        VALUES 
        ('admin', ?, 'CHIEF_RISK_OFFICER'),
        ('analyst', ?, 'FRAUD_ANALYST')
    """, (admin_pw, admin_pw))

    print("[SEED] Creating Customers (Rahul R A, Yedhu Krishnan G, Priya Sharma)...")
    user_pw = generate_password_hash("password123")
    
    customers_data = [
        ('Rahul R A', 'rahul@bank.com', '+919876543210', '124 MG Road, Bangalore, Karnataka', user_pw),
        ('Yedhu Krishnan G', 'yedhu@bank.com', '+919876543211', '45 Marine Drive, Kochi, Kerala', user_pw),
        ('Priya Sharma', 'priya@bank.com', '+919876543212', '78 Ring Road, New Delhi', user_pw)
    ]

    cursor.executemany("""
        INSERT INTO CUSTOMER (full_name, email, phone, address, password_hash)
        VALUES (?, ?, ?, ?, ?)
    """, customers_data)

    cursor.execute("SELECT customer_id FROM CUSTOMER WHERE email = 'rahul@bank.com'")
    rahul_id = cursor.fetchone()['customer_id']
    cursor.execute("SELECT customer_id FROM CUSTOMER WHERE email = 'yedhu@bank.com'")
    yedhu_id = cursor.fetchone()['customer_id']
    cursor.execute("SELECT customer_id FROM CUSTOMER WHERE email = 'priya@bank.com'")
    priya_id = cursor.fetchone()['customer_id']

    print("[SEED] Creating Credit Cards...")
    # Default PIN is '1234'
    pin_hash_1234 = generate_password_hash("1234")
    cards_data = [
        # Rahul's card matches the XX4821 card from the project slides!
        (rahul_id, '4532890123454821', 'Visa Signature', 150000.00, 115000.00, '2028-12-31', pin_hash_1234, 0, 'ACTIVE'),
        (rahul_id, '5105105105108890', 'Mastercard Gold', 100000.00, 95000.00, '2027-08-31', pin_hash_1234, 0, 'ACTIVE'),
        (yedhu_id, '4111222233339012', 'Visa Platinum', 200000.00, 185000.00, '2029-05-31', pin_hash_1234, 0, 'ACTIVE'),
        (priya_id, '6011000011117765', 'RuPay Select', 80000.00, 72000.00, '2028-03-31', pin_hash_1234, 0, 'ACTIVE')
    ]

    cursor.executemany("""
        INSERT INTO CARD (customer_id, card_number, card_type, credit_limit, available_limit, expiry_date, pin_hash, failed_pin_attempts, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, cards_data)

    cursor.execute("SELECT card_id FROM CARD WHERE card_number = '4532890123454821'")
    card1_id = cursor.fetchone()['card_id']
    cursor.execute("SELECT card_id FROM CARD WHERE card_number = '4111222233339012'")
    card3_id = cursor.fetchone()['card_id']

    print("[SEED] Creating Realistic Transactions...")
    now = datetime.now()
    
    # 1. Normal grocery transaction (APPROVED)
    t1_time = (now - timedelta(days=2, hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
        VALUES (?, 1850.00, ?, 'Reliance Fresh', 'Bangalore, India', 'APPROVED')
    """, (card1_id, t1_time))
    t1_id = cursor.lastrowid

    # 2. Fuel station transaction (APPROVED)
    t2_time = (now - timedelta(days=1, hours=6)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
        VALUES (?, 3200.00, ?, 'Indian Oil Fuel Station', 'Bangalore, India', 'APPROVED')
    """, (card1_id, t2_time))
    t2_id = cursor.lastrowid

    # 3. Suspicious transaction matching Slide 7 ("Rs. 24,500 at an online store, risk score 62")
    t3_time = (now - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
        VALUES (?, 24500.00, ?, 'Online Store Electronics', 'International Gateway', 'FLAGGED')
    """, (card1_id, t3_time))
    t3_id = cursor.lastrowid

    # 4. Critical fraud attempt (BLOCKED)
    t4_time = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
        VALUES (?, 85000.00, ?, 'Binance Crypto Exchange', 'Offshore / Unknown IP', 'BLOCKED')
    """, (card1_id, t4_time))
    t4_id = cursor.lastrowid

    # 5. Yedhu's normal transaction
    t5_time = (now - timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
        VALUES (?, 4500.00, ?, 'Lulu Hypermarket', 'Kochi, India', 'APPROVED')
    """, (card3_id, t5_time))

    print("[SEED] Creating Fraud Alerts for Flagged & Blocked Txns...")
    # Alert for t3 (Risk score 62, RF: 0.65, ISO: 0.55 -> Flagged)
    cursor.execute("""
        INSERT INTO FRAUD_ALERT (txn_id, rule_hit, risk_score, rf_prob, iso_score, alert_status, alert_time)
        VALUES (?, 'Unusual Amount & International Online Merchant', 62, 0.6500, 0.5500, 'NEW', ?)
    """, (t3_id, t3_time))
    a1_id = cursor.lastrowid

    # Alert for t4 (Risk score 86, RF: 0.92, ISO: 0.72 -> Blocked)
    cursor.execute("""
        INSERT INTO FRAUD_ALERT (txn_id, rule_hit, risk_score, rf_prob, iso_score, alert_status, alert_time)
        VALUES (?, 'Critical Risk: High-Risk Crypto Portal & Spike (Risk 86)', 86, 0.9200, 0.7200, 'BLOCKED', ?)
    """, (t4_id, t4_time))
    a2_id = cursor.lastrowid

    print("[SEED] Creating SMS Logs (Slide 8 templates)...")
    # SMS for t3 (Suspicious notice)
    sms_msg_t3 = "BANK ALERT: Rs.24,500 spent at Online Store Electronics on card XX4821 looks suspicious. Not you? Use chatbot or call bank."
    cursor.execute("""
        INSERT INTO SMS_LOG (alert_id, phone, message, sms_status, sent_time)
        VALUES (?, '+919876543210', ?, 'DELIVERED', ?)
    """, (a1_id, sms_msg_t3, t3_time))

    # SMS for t4 (Card blocked notice)
    sms_msg_t4 = "BANK ALERT: Card XX4821 is BLOCKED due to suspected fraud. Please contact your bank."
    cursor.execute("""
        INSERT INTO SMS_LOG (alert_id, phone, message, sms_status, sent_time)
        VALUES (?, '+919876543210', ?, 'DELIVERED', ?)
    """, (a2_id, sms_msg_t4, t4_time))

    print("[SEED] Creating Chatbot Sample Interaction (Slide 7)...")
    chat_time_1 = (now - timedelta(minutes=45)).strftime("%Y-%m-%d %H:%M:%S")
    chat_time_2 = (now - timedelta(minutes=44)).strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute("""
        INSERT INTO CHAT_LOG (customer_id, user_message, intent, bot_reply, chat_time)
        VALUES 
        (?, 'Why was my last payment flagged?', 'why_flagged', 
         'Your Rs. 24,500 payment at Online Store Electronics was flagged: risk score 62 (Unusual Amount & International Online Merchant). An SMS alert was sent to your mobile.', ?),
        (?, 'I did not make it. Block my card.', 'report_fraud',
         'Block request raised for card XX4821. The bank admin has been informed and card status updated to BLOCKED.', ?)
    """, (rahul_id, chat_time_1, rahul_id, chat_time_2))

    conn.commit()
    conn.close()
    print("[SUCCESS] Database successfully seeded with full project mock data!")

if __name__ == '__main__':
    seed_database()
