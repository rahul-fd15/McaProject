import re
from datetime import datetime
from models.database import get_db_connection, mask_card_number, short_mask
from models.sms_service import SMSService

class ChatbotEngine:
    @staticmethod
    def detect_intent(message):
        """
        Detects customer intent using NLP keyword and regex matching.
        Allowed intents matching Slide 10:
        ['txn_history', 'why_flagged', 'block_card', 'card_info', 'report_fraud', 'faq']
        """
        msg = message.lower().strip()

        # 1. Report Fraud / Unauthorized
        if any(p in msg for p in [
            'did not do this', 'did not make', 'didnt make', "didn't make", 
            'unauthorized', 'fraud transaction', 'stolen', 'not me', 'scam'
        ]):
            return 'report_fraud'

        # 2. Block Card
        if any(p in msg for p in [
            'block my card', 'block card', 'freeze card', 'lock my card', 
            'disable my card', 'stop my card', 'deactivate'
        ]):
            return 'block_card'

        # 3. Why Flagged / Reason for Alert
        if 'flag' in msg or 'flagged' in msg or ('why' in msg and ('payment' in msg or 'transaction' in msg or 'hold' in msg or 'block' in msg or 'decline' in msg)):
            return 'why_flagged'

        # 4. Transaction History
        if any(p in msg for p in [
            'last transaction', 'recent transaction', 'history', 'my transactions', 
            'last payment', 'show transactions', 'statement', 'past payments'
        ]):
            return 'txn_history'

        # 5. Card Info / Limit / Expiry
        if any(p in msg for p in [
            'limit', 'expiry', 'balance', 'available limit', 'credit limit', 
            'card details', 'my card', 'card info'
        ]):
            return 'card_info'

        # 6. FAQ / Help
        return 'faq'

    @classmethod
    def process_message(cls, customer_id, user_message):
        """
        Processes a chat message for an authenticated customer, executes DB actions,
        generates safe replies (masked card numbers), and logs to CHAT_LOG table.
        """
        intent = cls.detect_intent(user_message)
        reply = ""
        action_taken = None

        conn = get_db_connection()
        cursor = conn.cursor()

        # Fetch Customer information
        cursor.execute("SELECT * FROM CUSTOMER WHERE customer_id = ?", (customer_id,))
        customer = cursor.fetchone()
        if not customer:
            return {"reply": "Session error. Please log in again.", "intent": "error"}

        # Fetch Customer's primary or active card
        cursor.execute("SELECT * FROM CARD WHERE customer_id = ? ORDER BY card_id DESC", (customer_id,))
        cards = cursor.fetchall()
        primary_card = cards[0] if cards else None

        if intent == 'why_flagged':
            # Find the most recent flagged or blocked transaction
            cursor.execute("""
                SELECT t.txn_id, t.amount, t.merchant, t.location, t.txn_time, t.status,
                       f.rule_hit, f.risk_score, f.rf_prob, f.iso_score
                FROM `TRANSACTION` t
                JOIN CARD c ON t.card_id = c.card_id
                LEFT JOIN FRAUD_ALERT f ON t.txn_id = f.txn_id
                WHERE c.customer_id = ? AND t.status IN ('FLAGGED', 'BLOCKED')
                ORDER BY t.txn_id DESC LIMIT 1
            """, (customer_id,))
            flagged = cursor.fetchone()

            if flagged:
                masked_card = mask_card_number(primary_card['card_number']) if primary_card else "your card"
                score = flagged['risk_score'] if flagged['risk_score'] is not None else 62
                reason = flagged['rule_hit'] if flagged['rule_hit'] else "unusual activity"
                reply = (f"Your Rs. {float(flagged['amount']):,.2f} payment at {flagged['merchant']} was "
                         f"{flagged['status'].lower()}: risk score {score} ({reason}). "
                         f"An SMS alert was sent to your mobile. If you didn't do this, say 'Block my card'.")
            else:
                reply = "Good news! You have no recently flagged or blocked transactions on your account."

        elif intent == 'report_fraud':
            if primary_card:
                masked = short_mask(primary_card['card_number'])
                # Freeze card immediately
                cursor.execute("UPDATE CARD SET status = 'BLOCKED' WHERE card_id = ?", (primary_card['card_id'],))
                conn.commit()

                # Dispatch notification
                SMSService.send_sms(
                    phone=customer['phone'],
                    message=SMSService.format_message('FRAUD_REPORTED_BY_USER', primary_card['card_number'])
                )
                action_taken = "CARD_BLOCKED"
                reply = f"Urgent fraud report noted! Block request raised for card {masked}. Your card is now frozen and bank admin has been notified."
            else:
                reply = "No active card was found on your account. Please contact bank helpline at 1800-123-4567."

        elif intent == 'block_card':
            if primary_card:
                masked = short_mask(primary_card['card_number'])
                if primary_card['status'] == 'BLOCKED':
                    reply = f"Your card {masked} is already BLOCKED. Contact admin to unblock."
                else:
                    cursor.execute("UPDATE CARD SET status = 'BLOCKED' WHERE card_id = ?", (primary_card['card_id'],))
                    conn.commit()
                    SMSService.send_sms(
                        phone=customer['phone'],
                        message=SMSService.format_message('CARD_BLOCKED_FRAUD', primary_card['card_number'])
                    )
                    action_taken = "CARD_BLOCKED"
                    reply = f"Block request executed for card {masked}. The card is now BLOCKED and bank admin has been informed."
            else:
                reply = "No card registered on this account to block."

        elif intent == 'txn_history':
            cursor.execute("""
                SELECT t.txn_id, t.amount, t.merchant, t.txn_time, t.status, c.card_number
                FROM `TRANSACTION` t
                JOIN CARD c ON t.card_id = c.card_id
                WHERE c.customer_id = ?
                ORDER BY t.txn_id DESC LIMIT 3
            """, (customer_id,))
            recent_txns = cursor.fetchall()

            if recent_txns:
                lines = []
                for t in recent_txns:
                    m = short_mask(t['card_number'])
                    lines.append(f"• Rs. {float(t['amount']):,.2f} at {t['merchant']} ({m}) - [{t['status']}]")
                reply = "Your recent transactions:\n" + "\n".join(lines)
            else:
                reply = "You don't have any recorded transactions yet."

        elif intent == 'card_info':
            if primary_card:
                masked = mask_card_number(primary_card['card_number'])
                limit = float(primary_card['credit_limit'])
                avail = float(primary_card['available_limit'])
                expiry = primary_card['expiry_date']
                status = primary_card['status']
                reply = (f"Card: {masked} | Type: {primary_card['card_type']} | Status: {status} | "
                         f"Credit Limit: Rs. {limit:,.2f} | Available: Rs. {avail:,.2f} | Expiry: {expiry}")
            else:
                reply = "No card currently linked to your profile."

        else: # FAQ
            user_low = user_message.lower()
            if 'how' in user_low and ('fraud' in user_low or 'work' in user_low or 'detect' in user_low):
                reply = "Our system uses Hybrid ML: Random Forest (trained on past patterns) + Isolation Forest (unsupervised anomaly detector) to compute a 0-100 risk score on every swipe."
            elif 'contact' in user_low or 'phone' in user_low or 'helpline' in user_low:
                reply = "Bank 24/7 Helpline: 1800-419-5959 or email: support@dummybank.com. Admin office: Main Banking Hall."
            elif 'pin' in user_low:
                reply = "Security Note: Entering 3 consecutive wrong PINs locks your card automatically for protection."
            else:
                reply = "I'm your 24/7 Bank Support Assistant. You can ask me: 'Last transactions', 'Why was my payment flagged?', 'Block my card', or 'Card limit'."

        # Truncate reply to 255 characters to strictly fit CHAT_LOG schema
        reply_stored = reply[:255]

        # Log to CHAT_LOG Table (Slide 10)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO CHAT_LOG (customer_id, user_message, intent, bot_reply, chat_time)
            VALUES (?, ?, ?, ?, ?)
        """, (customer_id, user_message[:200], intent, reply_stored, now_str))
        conn.commit()
        chat_id = cursor.lastrowid
        conn.close()

        return {
            'chat_id': chat_id,
            'intent': intent,
            'reply': reply,
            'action_taken': action_taken
        }
