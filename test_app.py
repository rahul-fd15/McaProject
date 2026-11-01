import os
import sys

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from app import app
from seed_data import seed_database

def test_full_pipeline():
    print("==================================================================")
    print(" RUNNING AUTOMATED COMPREHENSIVE TEST SUITE                      ")
    print("==================================================================")

    # 1. Fresh seed
    seed_database()

    from models.database import get_db_connection
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT card_id FROM CARD WHERE card_number = '4532890123454821'")
    card1_id = c.fetchone()['card_id']
    c.execute("SELECT card_id FROM CARD WHERE card_number = '5105105105108890'")
    card2_id = c.fetchone()['card_id']
    conn.close()

    client = app.test_client()

    # Test 1: Landing Page
    res = client.get('/')
    assert res.status_code == 200, f"Landing page failed: {res.status_code}"
    assert b"Credit Card Fraud Detection System" in res.data
    print("[PASS] 1. Landing Page (/) accessible and rendered correctly.")

    # Test 2: Customer Login
    res = client.post('/login', data={'email': 'rahul@bank.com', 'password': 'password123'}, follow_redirects=True)
    assert res.status_code == 200
    assert b"My Issued Cards" in res.data
    print("[PASS] 2. Customer Authentication (/login) successful.")

    # Test 3: Normal Transaction (Score 0-39 -> APPROVED)
    res = client.post('/customer/transaction', data={
        'card_id': card1_id,
        'amount': '450.00',
        'merchant': 'Reliance Fresh Grocery',
        'location': 'Domestic Store',
        'pin': '1234'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['status'] == 'APPROVED'
    assert data['risk_score'] < 40
    print(f"[PASS] 3. Normal Transaction Approved: Risk Score = {data['risk_score']}, Status = {data['status']}")

    # Test 4: Suspicious Transaction (Score 40-69 -> FLAGGED + SMS)
    res = client.post('/customer/transaction', data={
        'card_id': card1_id,
        'amount': '24500.00',
        'merchant': 'Online Store Electronics',
        'location': 'International Gateway',
        'pin': '1234'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['status'] == 'FLAGGED'
    assert 40 <= data['risk_score'] < 70
    assert data['sms_dispatched'] is True
    print(f"[PASS] 4. Suspicious Transaction Flagged: Risk Score = {data['risk_score']}, Status = {data['status']}, SMS Dispatched = {data['sms_dispatched']}")

    # Test 5: Critical Fraud Transaction (Score >= 70 -> BLOCKED + SMS)
    res = client.post('/customer/transaction', data={
        'card_id': card1_id,
        'amount': '85000.00',
        'merchant': 'Binance Crypto Exchange',
        'location': 'Offshore / Moscow IP',
        'pin': '1234'
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['status'] == 'BLOCKED'
    assert data['risk_score'] >= 70
    assert data['sms_dispatched'] is True
    print(f"[PASS] 5. Critical Fraud Blocked: Risk Score = {data['risk_score']}, Status = {data['status']}, SMS Dispatched = {data['sms_dispatched']}")

    # Test 6: Wrong PIN Security Lock (Card 2)
    # 1st wrong attempt
    res1 = client.post('/customer/transaction', data={'card_id': card2_id, 'amount': '500', 'merchant': 'Shop', 'location': 'City', 'pin': '9999'})
    assert res1.status_code == 400
    # 2nd wrong attempt
    res2 = client.post('/customer/transaction', data={'card_id': card2_id, 'amount': '500', 'merchant': 'Shop', 'location': 'City', 'pin': '9999'})
    assert res2.status_code == 400
    # 3rd wrong attempt -> LOCKED!
    res3 = client.post('/customer/transaction', data={'card_id': card2_id, 'amount': '500', 'merchant': 'Shop', 'location': 'City', 'pin': '9999'})
    assert res3.status_code == 403
    d3 = res3.get_json()
    assert d3['decision'] == 'LOCKED'
    print(f"[PASS] 6. Security Rule: 3+ Failed PIN attempts locked card: {d3['message']}")

    # Test 7: Chatbot Support Engine
    res_chat1 = client.post('/api/chat', json={'message': 'Why was my last payment flagged?'})
    assert res_chat1.status_code == 200
    cdata1 = res_chat1.get_json()
    assert cdata1['intent'] == 'why_flagged'
    assert 'risk score' in cdata1['reply'].lower()
    print(f"[PASS] 7a. Chatbot 'why_flagged': {cdata1['reply']}")

    res_chat2 = client.post('/api/chat', json={'message': 'Show my last transactions'})
    assert res_chat2.status_code == 200
    cdata2 = res_chat2.get_json()
    assert cdata2['intent'] == 'txn_history'
    print(f"[PASS] 7b. Chatbot 'txn_history':\n{cdata2['reply']}")

    res_chat3 = client.post('/api/chat', json={'message': 'I did not make this transaction. Block my card.'})
    assert res_chat3.status_code == 200
    cdata3 = res_chat3.get_json()
    assert cdata3['intent'] == 'report_fraud'
    print(f"[PASS] 7c. Chatbot 'report_fraud': {cdata3['reply']}")

    # Test 8: Admin Authentication & Console
    admin_client = app.test_client()
    res_adm_login = admin_client.post('/admin/login', data={'username': 'admin', 'password': 'admin123'}, follow_redirects=True)
    assert res_adm_login.status_code == 200
    assert b"Bank Admin Fraud Operations Center" in res_adm_login.data
    print("[PASS] 8. Admin Authentication (/admin/login) successful.")

    # Test 9: Admin Alerts Review Desk
    res_alerts = admin_client.get('/admin/alerts')
    assert res_alerts.status_code == 200
    assert b"Fraud Alert Review Desk" in res_alerts.data
    print("[PASS] 9. Admin Fraud Alerts (/admin/alerts) rendered.")

    # Test 10: Admin Reports & CSV Export
    res_rep = admin_client.get('/admin/reports')
    assert res_rep.status_code == 200
    res_csv = admin_client.get('/admin/reports/export')
    assert res_csv.status_code == 200
    assert b"Txn ID,Customer,Card (Masked)" in res_csv.data
    print("[PASS] 10. Admin Reports and CSV Export working seamlessly.")

    # Test 11: Admin SMS & Chatbot Audit Logs
    res_sms = admin_client.get('/admin/sms-logs')
    assert res_sms.status_code == 200
    res_chat_log = admin_client.get('/admin/chat-logs')
    assert res_chat_log.status_code == 200
    print("[PASS] 11. Admin SMS Logs & Chatbot Logs accessible.")

    # Test 12: Admin Live ML Simulator
    res_sim = admin_client.post('/admin/simulator', data={
        'amount': '35000.00',
        'merchant': 'Luxury Jewelry Overseas',
        'location': 'International Gateway',
        'hour': '3'
    })
    assert res_sim.status_code == 200
    assert b"Model Prediction Output" in res_sim.data
    print("[PASS] 12. Live ML Fraud Simulator scored custom input correctly.")

    print("\n==================================================================")
    print(" ALL 12 PIPELINE & SYSTEM INTEGRATION TESTS PASSED 100%!          ")
    print("==================================================================")

if __name__ == '__main__':
    test_full_pipeline()
