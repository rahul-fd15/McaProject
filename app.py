import os
import sys
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
import io
import csv

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from config import Config
from models.database import init_db, get_db_connection, mask_card_number, short_mask
from models.ml_engine import ml_engine
from models.sms_service import SMSService
from models.chatbot_engine import ChatbotEngine

app = Flask(__name__)
app.config.from_object(Config)

# Ensure database exists
init_db()

# ---------------------------------------------------------
# Authentication Decorators
# ---------------------------------------------------------
def customer_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'customer_id' not in session:
            flash('Please log in to access your customer banking dashboard.', 'warning')
            return redirect(url_for('customer_login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'admin_id' not in session:
            flash('Admin authentication required.', 'danger')
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ---------------------------------------------------------
# Public & Landing Routes
# ---------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/about')
def about():
    return render_template('about.html')

# ---------------------------------------------------------
# Customer Authentication & Registration
# ---------------------------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def customer_login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM CUSTOMER WHERE LOWER(email) = ?", (email,))
        customer = cursor.fetchone()
        conn.close()

        if customer and check_password_hash(customer['password_hash'], password):
            session['customer_id'] = customer['customer_id']
            session['customer_name'] = customer['full_name']
            session['customer_email'] = customer['email']
            session['customer_phone'] = customer['phone']
            flash(f"Welcome back, {customer['full_name']}!", 'success')
            return redirect(url_for('customer_dashboard'))
        else:
            flash('Invalid email address or password. Please try again.', 'danger')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def customer_register():
    if request.method == 'POST':
        full_name = request.form.get('full_name', '').strip()
        email = request.form.get('email', '').strip().lower()
        phone = request.form.get('phone', '').strip()
        address = request.form.get('address', '').strip()
        password = request.form.get('password', '')
        pin = request.form.get('pin', '1234').strip()

        if not full_name or not email or not phone or not password:
            flash('Please fill in all mandatory fields.', 'danger')
            return render_template('register.html')

        conn = get_db_connection()
        cursor = conn.cursor()

        # Check existing email
        cursor.execute("SELECT customer_id FROM CUSTOMER WHERE LOWER(email) = ?", (email,))
        if cursor.fetchone():
            conn.close()
            flash('An account with this email already exists.', 'warning')
            return render_template('register.html')

        pw_hash = generate_password_hash(password)
        cursor.execute("""
            INSERT INTO CUSTOMER (full_name, email, phone, address, password_hash)
            VALUES (?, ?, ?, ?, ?)
        """, (full_name, email, phone, address, pw_hash))
        customer_id = cursor.lastrowid

        # Automatically issue an initial Visa Card for customer
        # Card number: 4532 + 8 random digits + 4 digits
        import random
        rand_mid = f"{random.randint(10000000, 99999999)}"
        rand_last = f"{random.randint(1000, 9999)}"
        new_card_num = f"4532{rand_mid[:4]}{rand_mid[4:]}{rand_last}"
        pin_hash = generate_password_hash(pin if len(pin) == 4 else "1234")
        expiry = (datetime.now().replace(year=datetime.now().year + 3)).strftime("%Y-%m-%d")

        cursor.execute("""
            INSERT INTO CARD (customer_id, card_number, card_type, credit_limit, available_limit, expiry_date, pin_hash, failed_pin_attempts, status)
            VALUES (?, ?, 'Visa Platinum', 100000.00, 100000.00, ?, ?, 0, 'ACTIVE')
        """, (customer_id, new_card_num, expiry, pin_hash))

        conn.commit()
        conn.close()

        flash('Registration successful! Your credit card has been generated. Please log in.', 'success')
        return redirect(url_for('customer_login'))

    return render_template('register.html')

@app.route('/logout')
def customer_logout():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    session.pop('customer_email', None)
    session.pop('customer_phone', None)
    flash('You have been logged out safely.', 'info')
    return redirect(url_for('customer_login'))

# ---------------------------------------------------------
# Customer Banking Dashboard & Transactions
# ---------------------------------------------------------
@app.route('/customer/dashboard')
@customer_login_required
def customer_dashboard():
    customer_id = session['customer_id']
    conn = get_db_connection()
    cursor = conn.cursor()

    # Customer profile
    cursor.execute("SELECT * FROM CUSTOMER WHERE customer_id = ?", (customer_id,))
    customer = cursor.fetchone()

    # Cards belonging to this customer
    cursor.execute("SELECT * FROM CARD WHERE customer_id = ? ORDER BY card_id ASC", (customer_id,))
    cards = cursor.fetchall()

    # Masked cards representation for frontend
    cards_list = []
    for c in cards:
        cards_list.append({
            'card_id': c['card_id'],
            'card_number_masked': mask_card_number(c['card_number']),
            'card_type': c['card_type'],
            'credit_limit': float(c['credit_limit']),
            'available_limit': float(c['available_limit']),
            'used_limit': float(c['credit_limit']) - float(c['available_limit']),
            'used_percent': round(((float(c['credit_limit']) - float(c['available_limit'])) / float(c['credit_limit'])) * 100, 1) if float(c['credit_limit']) > 0 else 0,
            'expiry_date': c['expiry_date'],
            'status': c['status'],
            'failed_pin_attempts': c['failed_pin_attempts']
        })

    # Recent transactions
    cursor.execute("""
        SELECT t.txn_id, t.amount, t.txn_time, t.merchant, t.location, t.status,
               c.card_number, f.risk_score, f.rule_hit, f.rf_prob, f.iso_score
        FROM `TRANSACTION` t
        JOIN CARD c ON t.card_id = c.card_id
        LEFT JOIN FRAUD_ALERT f ON t.txn_id = f.txn_id
        WHERE c.customer_id = ?
        ORDER BY t.txn_id DESC LIMIT 15
    """, (customer_id,))
    raw_txns = cursor.fetchall()

    transactions = []
    for t in raw_txns:
        transactions.append({
            'txn_id': t['txn_id'],
            'amount': float(t['amount']),
            'txn_time': t['txn_time'],
            'merchant': t['merchant'],
            'location': t['location'],
            'status': t['status'],
            'card_masked': short_mask(t['card_number']),
            'risk_score': t['risk_score'],
            'rule_hit': t['rule_hit'],
            'rf_prob': float(t['rf_prob']) if t['rf_prob'] is not None else None,
            'iso_score': float(t['iso_score']) if t['iso_score'] is not None else None
        })

    # Recent SMS messages sent to this customer
    cursor.execute("""
        SELECT s.sms_id, s.phone, s.message, s.sms_status, s.sent_time
        FROM SMS_LOG s
        WHERE s.phone = ?
        ORDER BY s.sms_id DESC LIMIT 5
    """, (customer['phone'],))
    recent_sms = cursor.fetchall()

    conn.close()
    return render_template('customer_dashboard.html',
                           customer=customer,
                           cards=cards_list,
                           transactions=transactions,
                           recent_sms=recent_sms)

# ---------------------------------------------------------
# Transaction Processing Module (Module 3 & Module 4)
# ---------------------------------------------------------
@app.route('/customer/transaction', methods=['POST'])
@customer_login_required
def process_transaction():
    customer_id = session['customer_id']
    card_id = request.form.get('card_id')
    amount_raw = request.form.get('amount')
    merchant = request.form.get('merchant', 'Online Merchant').strip()
    location = request.form.get('location', 'Domestic Gateway').strip()
    pin = request.form.get('pin', '').strip()

    try:
        amount = float(amount_raw)
        if amount <= 0:
            return jsonify({'success': False, 'message': 'Transaction amount must be greater than zero.'}), 400
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Invalid amount specified.'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()

    # Fetch card and ensure it belongs to this customer
    cursor.execute("SELECT * FROM CARD WHERE card_id = ? AND customer_id = ?", (card_id, customer_id))
    card = cursor.fetchone()

    if not card:
        conn.close()
        return jsonify({'success': False, 'message': 'Card not found or unauthorized.'}), 404

    cursor.execute("SELECT phone FROM CUSTOMER WHERE customer_id = ?", (customer_id,))
    customer_phone = cursor.fetchone()['phone']

    card_status = card['status']
    card_number = card['card_number']
    masked_short = short_mask(card_number)

    # 1. Check if card is currently blocked or locked
    if card_status in ('BLOCKED', 'LOCKED'):
        conn.close()
        return jsonify({
            'success': False,
            'decision': 'DECLINED',
            'message': f"Transaction declined: Card {masked_short} is currently {card_status}. Contact bank administration."
        }), 403

    # 2. Check Expiry Date
    try:
        expiry_dt = datetime.strptime(card['expiry_date'], "%Y-%m-%d").date()
        if expiry_dt < datetime.now().date():
            conn.close()
            return jsonify({
                'success': False,
                'decision': 'DECLINED',
                'message': f"Transaction declined: Card {masked_short} has expired."
            }), 400
    except Exception:
        pass

    # 3. Security Rule: PIN Verification & Failed Attempt Counter
    # (Slide 5: "Wrong-PIN rule stays independent of ML score: 3+ failed attempts blocks the card directly")
    if not check_password_hash(card['pin_hash'], pin):
        failed_count = card['failed_pin_attempts'] + 1
        if failed_count >= Config.MAX_FAILED_PIN_ATTEMPTS:
            # Lock card immediately
            cursor.execute("UPDATE CARD SET failed_pin_attempts = ?, status = 'LOCKED' WHERE card_id = ?",
                           (failed_count, card_id))
            conn.commit()

            # Record failed transaction
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
                VALUES (?, ?, ?, ?, ?, 'DECLINED')
            """, (card_id, amount, now_str, merchant, location))
            conn.commit()

            # Dispatch PIN locked SMS alert
            sms_msg = SMSService.format_message('PIN_LOCKED', card_number)
            SMSService.send_sms(customer_phone, sms_msg)
            conn.close()

            return jsonify({
                'success': False,
                'decision': 'LOCKED',
                'failed_attempts': failed_count,
                'message': f"Incorrect PIN entered {failed_count} times! Card {masked_short} has been LOCKED for your protection. An SMS alert has been sent."
            }), 403
        else:
            # Increment failed attempts
            cursor.execute("UPDATE CARD SET failed_pin_attempts = ? WHERE card_id = ?", (failed_count, card_id))
            conn.commit()
            conn.close()
            return jsonify({
                'success': False,
                'decision': 'DECLINED',
                'failed_attempts': failed_count,
                'remaining_attempts': Config.MAX_FAILED_PIN_ATTEMPTS - failed_count,
                'message': f"Incorrect PIN. {Config.MAX_FAILED_PIN_ATTEMPTS - failed_count} attempts remaining before card is locked."
            }), 400

    # PIN is correct -> Reset failed pin counter
    cursor.execute("UPDATE CARD SET failed_pin_attempts = 0 WHERE card_id = ?", (card_id,))
    conn.commit()

    # 4. Check Credit Limit
    available_limit = float(card['available_limit'])
    if amount > available_limit:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
            VALUES (?, ?, ?, ?, ?, 'DECLINED')
        """, (card_id, amount, now_str, merchant, location))
        conn.commit()
        conn.close()
        return jsonify({
            'success': False,
            'decision': 'DECLINED',
            'message': f"Transaction declined: Amount exceeds available credit limit (Available: Rs. {available_limit:,.2f})."
        }), 400

    # 5. Hybrid Machine Learning Fraud Evaluation (Module 4)
    ml_result = ml_engine.evaluate_risk(
        amount=amount,
        merchant=merchant,
        location=location,
        card_limit=card['credit_limit']
    )

    risk_score = ml_result['risk_score']
    rf_prob = ml_result['rf_prob']
    iso_score = ml_result['iso_score']
    decision = ml_result['decision'] # 'APPROVED', 'FLAGGED', or 'BLOCKED'
    rule_hit = ml_result['rule_hit']

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Record the transaction
    cursor.execute("""
        INSERT INTO `TRANSACTION` (card_id, amount, txn_time, merchant, location, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (card_id, amount, now_str, merchant, location, decision))
    conn.commit()
    txn_id = cursor.lastrowid

    sms_dispatched = False
    sms_message = None

    if decision == 'BLOCKED':
        # Score >= 70: Block card & send SMS
        cursor.execute("UPDATE CARD SET status = 'BLOCKED' WHERE card_id = ?", (card_id,))
        cursor.execute("""
            INSERT INTO FRAUD_ALERT (txn_id, rule_hit, risk_score, rf_prob, iso_score, alert_status, alert_time)
            VALUES (?, ?, ?, ?, ?, 'BLOCKED', ?)
        """, (txn_id, rule_hit, risk_score, rf_prob, iso_score, now_str))
        conn.commit()
        alert_id = cursor.lastrowid

        # Dispatch Blocked SMS
        sms_message = SMSService.format_message('CARD_BLOCKED_FRAUD', card_number)
        SMSService.send_sms(customer_phone, sms_message, alert_id=alert_id)
        sms_dispatched = True

    elif decision == 'FLAGGED':
        # Score 40-69: Flag transaction & send SMS alert
        # Deduct amount from available limit pending dispute
        new_avail = available_limit - amount
        cursor.execute("UPDATE CARD SET available_limit = ? WHERE card_id = ?", (new_avail, card_id))
        cursor.execute("""
            INSERT INTO FRAUD_ALERT (txn_id, rule_hit, risk_score, rf_prob, iso_score, alert_status, alert_time)
            VALUES (?, ?, ?, ?, ?, 'NEW', ?)
        """, (txn_id, rule_hit, risk_score, rf_prob, iso_score, now_str))
        conn.commit()
        alert_id = cursor.lastrowid

        # Dispatch Suspicious SMS Alert
        sms_message = SMSService.format_message('SUSPICIOUS_TXN', card_number, amount=amount, merchant=merchant)
        SMSService.send_sms(customer_phone, sms_message, alert_id=alert_id)
        sms_dispatched = True

    else: # APPROVED (Score 0-39)
        new_avail = available_limit - amount
        cursor.execute("UPDATE CARD SET available_limit = ? WHERE card_id = ?", (new_avail, card_id))
        conn.commit()

    conn.close()

    return jsonify({
        'success': True,
        'txn_id': txn_id,
        'amount': amount,
        'merchant': merchant,
        'status': decision,
        'risk_score': risk_score,
        'rf_prob': rf_prob,
        'iso_score': iso_score,
        'rule_hit': rule_hit,
        'sms_dispatched': sms_dispatched,
        'sms_message': sms_message
    })

# ---------------------------------------------------------
# Chatbot Support API (Module 6)
# ---------------------------------------------------------
@app.route('/api/chat', methods=['POST'])
@customer_login_required
def chat_api():
    customer_id = session['customer_id']
    data = request.get_json() or {}
    message = data.get('message', '').strip()

    if not message:
        return jsonify({'reply': 'Please type a question or instruction.', 'intent': 'empty'})

    result = ChatbotEngine.process_message(customer_id, message)
    return jsonify(result)

@app.route('/api/customer/recent-sms')
@customer_login_required
def get_recent_customer_sms():
    phone = session.get('customer_phone')
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT sms_id, message, sms_status, sent_time
        FROM SMS_LOG
        WHERE phone = ?
        ORDER BY sms_id DESC LIMIT 5
    """, (phone,))
    logs = cursor.fetchall()
    conn.close()

    res = []
    for l in logs:
        res.append({
            'sms_id': l['sms_id'],
            'message': l['message'],
            'status': l['sms_status'],
            'sent_time': l['sent_time']
        })
    return jsonify({'sms_list': res})

# ---------------------------------------------------------
# Bank Admin Authentication & Portal
# ---------------------------------------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ADMIN WHERE username = ?", (username,))
        admin = cursor.fetchone()
        conn.close()

        if admin and check_password_hash(admin['password_hash'], password):
            session['admin_id'] = admin['admin_id']
            session['admin_username'] = admin['username']
            session['admin_role'] = admin['role']
            flash(f"Welcome, Admin {admin['username']}.", 'success')
            return redirect(url_for('admin_dashboard'))
        else:
            flash('Invalid admin credentials.', 'danger')

    return render_template('admin_login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_username', None)
    session.pop('admin_role', None)
    flash('Logged out of Admin Portal.', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_login_required
def admin_dashboard():
    conn = get_db_connection()
    cursor = conn.cursor()

    # KPI Metrics
    cursor.execute("SELECT COUNT(*) FROM `TRANSACTION`")
    total_txns = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM `TRANSACTION` WHERE status = 'APPROVED'")
    approved_txns = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM `TRANSACTION` WHERE status = 'FLAGGED'")
    flagged_txns = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM `TRANSACTION` WHERE status = 'BLOCKED'")
    blocked_txns = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM CARD WHERE status = 'BLOCKED'")
    blocked_cards = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM CUSTOMER")
    total_customers = cursor.fetchone()[0]

    # Calculate blocked fraud volume
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM `TRANSACTION` WHERE status = 'BLOCKED'")
    prevented_loss = cursor.fetchone()[0]

    # Live Recent Transactions
    cursor.execute("""
        SELECT t.txn_id, t.amount, t.txn_time, t.merchant, t.location, t.status,
               c.card_number, cust.full_name, f.risk_score, f.rf_prob, f.iso_score
        FROM `TRANSACTION` t
        JOIN CARD c ON t.card_id = c.card_id
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id
        LEFT JOIN FRAUD_ALERT f ON t.txn_id = f.txn_id
        ORDER BY t.txn_id DESC LIMIT 10
    """)
    recent_txns = cursor.fetchall()

    txns_data = []
    for r in recent_txns:
        txns_data.append({
            'txn_id': r['txn_id'],
            'amount': float(r['amount']),
            'txn_time': r['txn_time'],
            'merchant': r['merchant'],
            'location': r['location'],
            'status': r['status'],
            'customer_name': r['full_name'],
            'card_masked': short_mask(r['card_number']),
            'risk_score': r['risk_score'],
            'rf_prob': float(r['rf_prob']) if r['rf_prob'] is not None else None,
            'iso_score': float(r['iso_score']) if r['iso_score'] is not None else None
        })

    # Risk score distribution for charts
    cursor.execute("""
        SELECT 
            SUM(CASE WHEN risk_score < 40 THEN 1 ELSE 0 END) as low_risk,
            SUM(CASE WHEN risk_score >= 40 AND risk_score < 70 THEN 1 ELSE 0 END) as med_risk,
            SUM(CASE WHEN risk_score >= 70 THEN 1 ELSE 0 END) as high_risk
        FROM FRAUD_ALERT
    """)
    risk_dist = cursor.fetchone()

    conn.close()

    metrics = {
        'total_txns': total_txns,
        'approved_txns': approved_txns,
        'flagged_txns': flagged_txns,
        'blocked_txns': blocked_txns,
        'blocked_cards': blocked_cards,
        'total_customers': total_customers,
        'prevented_loss': float(prevented_loss),
        'fraud_rate': round(((flagged_txns + blocked_txns) / max(total_txns, 1)) * 100, 2)
    }

    return render_template('admin_dashboard.html',
                           metrics=metrics,
                           recent_txns=txns_data,
                           risk_dist=risk_dist)

# ---------------------------------------------------------
# Admin Fraud Alerts Review & Actions
# ---------------------------------------------------------
@app.route('/admin/alerts')
@admin_login_required
def admin_alerts():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT f.alert_id, f.txn_id, f.rule_hit, f.risk_score, f.rf_prob, f.iso_score, f.alert_status, f.alert_time,
               t.amount, t.merchant, t.location, t.status as txn_status,
               c.card_id, c.card_number, c.status as card_status,
               cust.customer_id, cust.full_name, cust.phone
        FROM FRAUD_ALERT f
        JOIN `TRANSACTION` t ON f.txn_id = t.txn_id
        JOIN CARD c ON t.card_id = c.card_id
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id
        ORDER BY f.alert_id DESC
    """)
    alerts = cursor.fetchall()
    conn.close()

    alerts_list = []
    for a in alerts:
        alerts_list.append({
            'alert_id': a['alert_id'],
            'txn_id': a['txn_id'],
            'rule_hit': a['rule_hit'],
            'risk_score': a['risk_score'],
            'rf_prob': float(a['rf_prob']),
            'iso_score': float(a['iso_score']),
            'alert_status': a['alert_status'],
            'alert_time': a['alert_time'],
            'amount': float(a['amount']),
            'merchant': a['merchant'],
            'location': a['location'],
            'txn_status': a['txn_status'],
            'card_id': a['card_id'],
            'card_masked': mask_card_number(a['card_number']),
            'short_masked': short_mask(a['card_number']),
            'card_status': a['card_status'],
            'customer_name': a['full_name'],
            'customer_phone': a['phone']
        })

    return render_template('admin_alerts.html', alerts=alerts_list)

@app.route('/admin/alert/action', methods=['POST'])
@admin_login_required
def admin_alert_action():
    alert_id = request.form.get('alert_id')
    action = request.form.get('action') # 'BLOCK', 'UNBLOCK', 'DISMISS'

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT f.alert_id, c.card_id, c.card_number, cust.phone
        FROM FRAUD_ALERT f
        JOIN `TRANSACTION` t ON f.txn_id = t.txn_id
        JOIN CARD c ON t.card_id = c.card_id
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id
        WHERE f.alert_id = ?
    """, (alert_id,))
    data = cursor.fetchone()

    if not data:
        conn.close()
        flash('Alert not found.', 'danger')
        return redirect(url_for('admin_alerts'))

    card_id = data['card_id']
    card_number = data['card_number']
    phone = data['phone']

    if action == 'BLOCK':
        cursor.execute("UPDATE CARD SET status = 'BLOCKED' WHERE card_id = ?", (card_id,))
        cursor.execute("UPDATE FRAUD_ALERT SET alert_status = 'BLOCKED' WHERE alert_id = ?", (alert_id,))
        conn.commit()
        msg = SMSService.format_message('ADMIN_STATUS_CHANGE', card_number, details='BLOCKED')
        SMSService.send_sms(phone, msg, alert_id=alert_id)
        flash(f'Card {short_mask(card_number)} has been BLOCKED and customer alerted via SMS.', 'success')

    elif action == 'UNBLOCK':
        cursor.execute("UPDATE CARD SET status = 'ACTIVE', failed_pin_attempts = 0 WHERE card_id = ?", (card_id,))
        cursor.execute("UPDATE FRAUD_ALERT SET alert_status = 'REVIEWED' WHERE alert_id = ?", (alert_id,))
        conn.commit()
        msg = SMSService.format_message('ADMIN_STATUS_CHANGE', card_number, details='ACTIVE (Unblocked)')
        SMSService.send_sms(phone, msg, alert_id=alert_id)
        flash(f'Card {short_mask(card_number)} has been UNBLOCKED and restored.', 'success')

    elif action == 'DISMISS':
        cursor.execute("UPDATE FRAUD_ALERT SET alert_status = 'DISMISSED' WHERE alert_id = ?", (alert_id,))
        conn.commit()
        flash(f'Alert #{alert_id} has been dismissed as reviewed false positive.', 'info')

    conn.close()
    return redirect(url_for('admin_alerts'))

# ---------------------------------------------------------
# Admin Card Management
# ---------------------------------------------------------
@app.route('/admin/cards')
@admin_login_required
def admin_cards():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT c.*, cust.full_name, cust.email, cust.phone
        FROM CARD c
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id
        ORDER BY c.card_id ASC
    """)
    cards = cursor.fetchall()
    conn.close()

    cards_list = []
    for c in cards:
        cards_list.append({
            'card_id': c['card_id'],
            'customer_name': c['full_name'],
            'customer_email': c['email'],
            'phone': c['phone'],
            'card_number_masked': mask_card_number(c['card_number']),
            'short_masked': short_mask(c['card_number']),
            'card_type': c['card_type'],
            'credit_limit': float(c['credit_limit']),
            'available_limit': float(c['available_limit']),
            'expiry_date': c['expiry_date'],
            'failed_pin_attempts': c['failed_pin_attempts'],
            'status': c['status']
        })

    return render_template('admin_cards.html', cards=cards_list)

@app.route('/admin/cards/toggle', methods=['POST'])
@admin_login_required
def admin_card_toggle():
    card_id = request.form.get('card_id')
    new_status = request.form.get('status') # 'ACTIVE' or 'BLOCKED'

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT c.card_number, cust.phone 
        FROM CARD c 
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id 
        WHERE c.card_id = ?
    """, (card_id,))
    row = cursor.fetchone()

    if row:
        cursor.execute("UPDATE CARD SET status = ?, failed_pin_attempts = 0 WHERE card_id = ?", (new_status, card_id))
        conn.commit()
        msg = SMSService.format_message('ADMIN_STATUS_CHANGE', row['card_number'], details=new_status)
        SMSService.send_sms(row['phone'], msg)
        flash(f"Card {short_mask(row['card_number'])} status updated to {new_status}.", 'success')

    conn.close()
    return redirect(url_for('admin_cards'))

# ---------------------------------------------------------
# Admin Reports & Export (Module 5)
# ---------------------------------------------------------
@app.route('/admin/reports')
@admin_login_required
def admin_reports():
    status_filter = request.args.get('status', 'ALL')
    merchant_filter = request.args.get('merchant', '').strip()
    risk_filter = request.args.get('risk_band', 'ALL')

    conn = get_db_connection()
    cursor = conn.cursor()

    query = """
        SELECT t.txn_id, t.amount, t.txn_time, t.merchant, t.location, t.status,
               c.card_number, cust.full_name,
               f.risk_score, f.rf_prob, f.iso_score, f.rule_hit
        FROM `TRANSACTION` t
        JOIN CARD c ON t.card_id = c.card_id
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id
        LEFT JOIN FRAUD_ALERT f ON t.txn_id = f.txn_id
        WHERE 1=1
    """
    params = []

    if status_filter != 'ALL':
        query += " AND t.status = ?"
        params.append(status_filter)

    if merchant_filter:
        query += " AND LOWER(t.merchant) LIKE ?"
        params.append(f"%{merchant_filter.lower()}%")

    if risk_filter == 'LOW':
        query += " AND (f.risk_score IS NULL OR f.risk_score < 40)"
    elif risk_filter == 'MEDIUM':
        query += " AND f.risk_score >= 40 AND f.risk_score < 70"
    elif risk_filter == 'HIGH':
        query += " AND f.risk_score >= 70"

    query += " ORDER BY t.txn_id DESC"
    cursor.execute(query, params)
    records = cursor.fetchall()
    conn.close()

    report_data = []
    for r in records:
        report_data.append({
            'txn_id': r['txn_id'],
            'amount': float(r['amount']),
            'txn_time': r['txn_time'],
            'merchant': r['merchant'],
            'location': r['location'],
            'status': r['status'],
            'customer_name': r['full_name'],
            'card_masked': short_mask(r['card_number']),
            'risk_score': r['risk_score'] if r['risk_score'] is not None else 0,
            'rf_prob': float(r['rf_prob']) if r['rf_prob'] is not None else 0.0,
            'iso_score': float(r['iso_score']) if r['iso_score'] is not None else 0.0,
            'rule_hit': r['rule_hit'] if r['rule_hit'] else 'Standard Clean'
        })

    return render_template('admin_reports.html',
                           reports=report_data,
                           status_filter=status_filter,
                           merchant_filter=merchant_filter,
                           risk_filter=risk_filter)

@app.route('/admin/reports/export')
@admin_login_required
def export_reports_csv():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.txn_id, cust.full_name, c.card_number, t.amount, t.txn_time, t.merchant, t.location, t.status,
               COALESCE(f.risk_score, 0) as risk_score, 
               COALESCE(f.rf_prob, 0.0) as rf_prob, 
               COALESCE(f.iso_score, 0.0) as iso_score,
               COALESCE(f.rule_hit, 'Normal') as rule_hit
        FROM `TRANSACTION` t
        JOIN CARD c ON t.card_id = c.card_id
        JOIN CUSTOMER cust ON c.customer_id = cust.customer_id
        LEFT JOIN FRAUD_ALERT f ON t.txn_id = f.txn_id
        ORDER BY t.txn_id DESC
    """)
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Txn ID', 'Customer', 'Card (Masked)', 'Amount (INR)', 'Time', 'Merchant', 'Location', 'Status', 'Risk Score', 'RF Prob', 'ISO Score', 'Rule Hit'])

    for r in rows:
        writer.writerow([
            r['txn_id'],
            r['full_name'],
            short_mask(r['card_number']),
            r['amount'],
            r['txn_time'],
            r['merchant'],
            r['location'],
            r['status'],
            r['risk_score'],
            r['rf_prob'],
            r['iso_score'],
            r['rule_hit']
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=Fraud_Detection_Transaction_Report.csv"}
    )

# ---------------------------------------------------------
# Admin SMS & Chat Audit Logs
# ---------------------------------------------------------
@app.route('/admin/sms-logs')
@admin_login_required
def admin_sms_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.sms_id, s.alert_id, s.phone, s.message, s.sms_status, s.sent_time,
               f.risk_score, f.rule_hit
        FROM SMS_LOG s
        LEFT JOIN FRAUD_ALERT f ON s.alert_id = f.alert_id
        ORDER BY s.sms_id DESC
    """)
    logs = cursor.fetchall()
    conn.close()
    return render_template('admin_sms_logs.html', logs=logs)

@app.route('/admin/chat-logs')
@admin_login_required
def admin_chat_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cl.chat_id, cl.user_message, cl.intent, cl.bot_reply, cl.chat_time,
               cust.full_name, cust.email
        FROM CHAT_LOG cl
        JOIN CUSTOMER cust ON cl.customer_id = cust.customer_id
        ORDER BY cl.chat_id DESC
    """)
    logs = cursor.fetchall()
    conn.close()
    return render_template('admin_chat_logs.html', logs=logs)

# ---------------------------------------------------------
# Interactive ML Fraud Simulator (Sandbox for Viva/Demo)
# ---------------------------------------------------------
@app.route('/admin/simulator', methods=['GET', 'POST'])
@admin_login_required
def admin_simulator():
    simulation_result = None
    sample_type = 'custom'

    if request.method == 'POST':
        sample_type = request.form.get('sample_type', 'custom')
        amount = float(request.form.get('amount', 5000.0))
        merchant = request.form.get('merchant', 'Online Retail').strip()
        location = request.form.get('location', 'Domestic Gateway').strip()
        hour = int(request.form.get('hour', 14))

        custom_v = None
        # Check if user entered custom V components
        v_raw = request.form.get('v_components', '').strip()
        if v_raw:
            try:
                custom_v = [float(x.strip()) for x in v_raw.split(',') if x.strip()]
                if len(custom_v) != 28:
                    custom_v = None
            except Exception:
                custom_v = None

        simulation_result = ml_engine.evaluate_risk(
            amount=amount,
            merchant=merchant,
            location=location,
            hour=hour,
            custom_v=custom_v
        )
        simulation_result['input_amount'] = amount
        simulation_result['input_merchant'] = merchant
        simulation_result['input_location'] = location
        simulation_result['input_hour'] = hour

    return render_template('admin_simulator.html',
                           result=simulation_result,
                           sample_type=sample_type)

if __name__ == '__main__':
    print("==================================================================")
    print(" CREDIT CARD FRAUD DETECTION SYSTEM (Dummy Bank Implementation)   ")
    print(" Rahul R A & Yedhu Krishnan G - MCA Mini Project                  ")
    print(" Hybrid ML: Random Forest (70%) + Isolation Forest (30%)          ")
    print(" Server starting on: http://127.0.0.1:5000                        ")
    print("==================================================================")
    app.run(host='127.0.0.1', port=5000, debug=True)
