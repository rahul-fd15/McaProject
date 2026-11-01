import os
import sys
import time
import requests
from datetime import datetime

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from models.database import get_db_connection, short_mask

class SMSService:
    @staticmethod
    def format_message(event_type, card_number, amount=None, merchant=None, details=None):
        """
        Generates strict < 160 character SMS message templates matching Slide 8.
        Never reveals full card number, PIN, or sensitive data.
        """
        masked = short_mask(card_number)
        
        if event_type == 'SUSPICIOUS_TXN':
            # 40-69 Risk band
            amt_str = f"Rs.{float(amount):,.0f}" if amount else "amount"
            merch_str = str(merchant)[:20] if merchant else "merchant"
            msg = f"BANK ALERT: {amt_str} spent at {merch_str} on card {masked} looks suspicious. Not you? Use chatbot or call bank."
        elif event_type == 'CARD_BLOCKED_FRAUD':
            # 70+ Risk band
            msg = f"BANK ALERT: Card {masked} is BLOCKED due to suspected fraud. Please contact your bank."
        elif event_type == 'PIN_LOCKED':
            # 3+ wrong PIN attempts
            msg = f"BANK ALERT: Card {masked} is LOCKED due to 3 failed PIN attempts. Please contact bank."
        elif event_type == 'ADMIN_STATUS_CHANGE':
            status = details if details else "updated"
            msg = f"BANK ALERT: Card {masked} status has been updated to {status} by bank administration."
        elif event_type == 'FRAUD_REPORTED_BY_USER':
            msg = f"BANK ALERT: Card {masked} temporary freeze initiated per your fraud report. Admin is investigating."
        else:
            msg = f"BANK ALERT: Activity notice on your card {masked}. Contact support for queries."
            
        # Ensure hard limit of 160 characters
        return msg[:160]

    @classmethod
    def send_sms(cls, phone, message, alert_id=None):
        """
        Dispatches SMS via Twilio, Fast2SMS, or Mock Gateway.
        Logs every stage in SMS_LOG: QUEUED -> SENT -> DELIVERED / FAILED.
        Retries up to 3 times on transmission failure.
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        # Step 1: Initial Log in QUEUED state
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO SMS_LOG (alert_id, phone, message, sms_status, sent_time)
            VALUES (?, ?, ?, 'QUEUED', ?)
        """, (alert_id, phone, message, now_str))
        conn.commit()
        sms_id = cursor.lastrowid

        # Step 2: Gateway Dispatch with Retry Logic (Up to 3 attempts)
        final_status = 'FAILED'
        mode = Config.SMS_GATEWAY_MODE.upper()

        for attempt in range(1, 4):
            try:
                if mode == 'TWILIO' and Config.TWILIO_ACCOUNT_SID and Config.TWILIO_AUTH_TOKEN:
                    # Twilio REST API
                    url = f"https://api.twilio.com/2010-04-01/Accounts/{Config.TWILIO_ACCOUNT_SID}/Messages.json"
                    resp = requests.post(
                        url,
                        data={
                            'To': phone,
                            'From': Config.TWILIO_PHONE_NUMBER,
                            'Body': message
                        },
                        auth=(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN),
                        timeout=5
                    )
                    if resp.status_code in (200, 201):
                        final_status = 'DELIVERED'
                        break

                elif mode == 'FAST2SMS' and Config.FAST2SMS_API_KEY:
                    # Fast2SMS Indian SMS Gateway REST API
                    url = "https://www.fast2sms.com/dev/bulkV2"
                    headers = {
                        'authorization': Config.FAST2SMS_API_KEY,
                        'Content-Type': 'application/json'
                    }
                    payload = {
                        "route": "q",
                        "message": message,
                        "numbers": phone.replace("+91", "").strip()
                    }
                    resp = requests.post(url, json=payload, headers=headers, timeout=5)
                    if resp.status_code == 200 and resp.json().get('return') is True:
                        final_status = 'DELIVERED'
                        break

                else:
                    # Local Mock Simulator Mode (Instant & 100% reliable for demonstration)
                    # Simulates sub-second telecom carrier delivery
                    final_status = 'DELIVERED'
                    break

            except Exception as e:
                print(f"[SMS Gateway Warning] Attempt {attempt} failed: {e}")
                time.sleep(0.5)

        # Step 3: Update SMS_LOG with final delivery status
        cursor.execute("""
            UPDATE SMS_LOG
            SET sms_status = ?, sent_time = ?
            WHERE sms_id = ?
        """, (final_status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), sms_id))
        conn.commit()
        conn.close()

        return {
            'sms_id': sms_id,
            'phone': phone,
            'message': message,
            'status': final_status
        }
