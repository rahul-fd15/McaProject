# Credit Card Fraud Detection System Implemented on a Bank System

> **MCA Mini Project – First Review**  
> **Presented by:** Rahul R A &bull; Yedhu Krishnan G  
> **Technology Stack:** Python 3.14 &bull; Flask &bull; scikit-learn (Random Forest & Isolation Forest) &bull; SQLite / MySQL &bull; Bootstrap 5 &bull; SMS Gateway API  

---

## 1. Project Overview & Abstract

Credit card fraud is an escalating problem in online and retail banking. As transaction volumes surge, traditional rule-based filters struggle against zero-day and novel fraud schemes.

This project delivers a complete, production-grade **Credit Card Fraud Detection System** seamlessly integrated into a **Dummy Bank Application**. Customers can register, manage issued cards, execute payments, inspect transaction history, and receive instant SMS notifications.

Every transaction is screened in real time by a **Hybrid Machine Learning Engine**:
1. **Random Forest Classifier (Supervised)**: Learns known fraud patterns from labelled past transaction data (Kaggle dataset).
2. **Isolation Forest Anomaly Detector (Unsupervised)**: Catches new, unseen, or novel outlier patterns without requiring labels.

Their predictions are blended into a unified **Risk Score (0–100)**:
$$\text{Risk Score} = 0.7 \times (\text{RF Fraud Probability} \times 100) + 0.3 \times (\text{Isolation Forest Anomaly Score} \times 100)$$

Based on the calculated risk score:
- **0 – 39**: **Approved** (Standard transaction)
- **40 – 69**: **Flagged & SMS Alert Sent** (Suspicious behavior)
- **70 and above**: **Card Blocked & SMS Alert Sent** (Critical fraud threat)

The bank application also includes an intelligent **Customer Support Chatbot** for querying recent transactions, explaining why payments were flagged, and raising immediate card freeze requests, alongside an automated **SMS Notification Tool** with full lifecycle audit logging (`QUEUED` $\to$ `SENT` $\to$ `DELIVERED`).

---

## 2. Seven Functional Project Modules

| # | Module Name | Description |
|---|---|---|
| **1** | **Customer Module** | Register, log in, view credit cards & credit limits, execute card payments, review history, receive SMS alerts, and request card freeze. |
| **2** | **Bank Admin Module** | Role-based admin console, monitor live transactions, review fraud alerts, freeze/unblock cards, and analyze system KPIs. |
| **3** | **Transaction Processing Module** | Validates card status, expiry date, available limit, and enforces the 3+ wrong PIN security lockout rule. |
| **4** | **Fraud Detection Module (Hybrid ML)** | Evaluates transactions with Random Forest and Isolation Forest, calculating the combined 0–100 risk score and rule hits. |
| **5** | **Alert & Report Module** | Persists flagged and blocked transactions in `FRAUD_ALERT`, manages review workflows, and generates exportable CSV/print reports. |
| **6** | **Chatbot Support Module** | 24/7 Conversational AI assistant supporting 6 classified intents (`txn_history`, `why_flagged`, `block_card`, `card_info`, `report_fraud`, `faq`) with masked card numbers. |
| **7** | **SMS Notification Module** | Dispatches instant alert SMS under 160 characters with masked card numbers (e.g. `XX4821`) via Twilio/Fast2SMS/Mock Gateway with retry tracking. |

---

## 3. Database Architecture (Data Stores D1–D7)

The database schema matches the relational design from the project specification:

```
[CUSTOMER] (D1) ─── 1:N ───< [CARD] (D2) ─── 1:N ───< [TRANSACTION] (D3)
                                                               │
                                                              1:0..1
                                                               v
                                                      [FRAUD_ALERT] (D4)
                                                               │
                                                              1:N
                                                               v
                                                          [SMS_LOG] (D6)

[CUSTOMER] (D1) ─── 1:N ───< [CHAT_LOG] (D7)
[ADMIN] (D5) (System Operators)
```

### Table Definitions

1. **`CUSTOMER` (D1)**: `customer_id` (PK), `full_name`, `email`, `phone`, `address`, `password_hash`, `created_at`
2. **`CARD` (D2)**: `card_id` (PK), `customer_id` (FK), `card_number` (Unique), `card_type`, `credit_limit`, `available_limit`, `expiry_date`, `pin_hash`, `failed_pin_attempts`, `status` (`ACTIVE`, `BLOCKED`, `LOCKED`)
3. **`TRANSACTION` (D3)**: `txn_id` (PK), `card_id` (FK), `amount`, `txn_time`, `merchant`, `location`, `status` (`APPROVED`, `FLAGGED`, `BLOCKED`, `DECLINED`)
4. **`FRAUD_ALERT` (D4)**: `alert_id` (PK), `txn_id` (FK), `rule_hit`, `risk_score` (0–100), `rf_prob` (0.0–1.0), `iso_score` (0.0–1.0), `alert_status` (`NEW`, `REVIEWED`, `DISMISSED`, `BLOCKED`), `alert_time`
5. **`ADMIN` (D5)**: `admin_id` (PK), `username`, `password_hash`, `role`
6. **`SMS_LOG` (D6)**: `sms_id` (PK), `alert_id` (FK), `phone`, `message` ($\le 160$ chars), `sms_status` (`QUEUED`, `SENT`, `DELIVERED`, `FAILED`), `sent_time`
7. **`CHAT_LOG` (D7)**: `chat_id` (PK), `customer_id` (FK), `user_message`, `intent`, `bot_reply`, `chat_time`

---

## 4. Hybrid Machine Learning Pipeline

### Why Both Random Forest and Isolation Forest?
- **Random Forest (Supervised)** excels at recognizing known historical fraud patterns, learning decision boundaries across $V_1 \dots V_{28}$, Amount, and Time.
- **Isolation Forest (Unsupervised)** requires no labels and isolates anomalies by recursively partitioning features. Anomalies need significantly fewer splits to isolate:
  $$s(x, n) = 2^{-\frac{E[h(x)]}{c(n)}}$$
  Where $h(x)$ is path length and $c(n)$ is average path length. Normal points sit deep ($s \le 0.5$); outliers isolate near the root ($s \to 1.0$).
- **Combined Benefit**: Random Forest catches known recurring fraud; Isolation Forest catches zero-day novel fraud patterns.

---

## 5. Security Rules

### Failed PIN Security Lockout
- **Rule**: Entering 3 consecutive incorrect PINs immediately locks the card (`CARD.failed_pin_attempts >= 3` $\to$ `status = 'LOCKED'`).
- **Independence**: This rule functions independently of the ML score.
- **Action**: An instant SMS is dispatched:
  `"BANK ALERT: Card XX4821 is LOCKED due to 3 failed PIN attempts. Please contact bank."`

---

## 6. Demo Accounts & Credentials

### Customer Logins:
- **Rahul R A**: `rahul@bank.com` | Password: `password123` | Card: `...4821` | PIN: `1234`
- **Yedhu Krishnan G**: `yedhu@bank.com` | Password: `password123` | Card: `...9012` | PIN: `1234`
- **Priya Sharma**: `priya@bank.com` | Password: `password123` | Card: `...7765` | PIN: `1234`

### Bank Admin Logins:
- **Chief Risk Officer**: `admin` | Password: `admin123`
- **Fraud Analyst**: `analyst` | Password: `admin123`

---

## 7. How to Run the Project

### Prerequisites
- Python 3.10+ (Verified on Python 3.14)
- Pip

### Step 1: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 2: Seed the Database
```bash
python seed_data.py
```

### Step 3: Train / Verify ML Models
```bash
python models/train_models.py
```

### Step 4: Start the Flask Application
```bash
python app.py
```
Open your browser at: **`http://127.0.0.1:5000`**

---

## 8. Viva Demonstration Guide

1. **Normal Purchase (Score 0–39)**:
   - Merchant: `Reliance Fresh`, Amount: `Rs. 1,450`, PIN: `1234`.
   - **Result**: Approved immediately. Low risk score.
2. **Suspicious Spike (Score 40–69)**:
   - Merchant: `Online Store Electronics`, Amount: `Rs. 24,500`, Location: `International Gateway`, PIN: `1234`.
   - **Result**: Flagged with SMS alert. Matches Slide 7 sample dialogue.
3. **Critical Fraud Attempt (Score 70+)**:
   - Merchant: `Binance Crypto Exchange`, Amount: `Rs. 85,000`, Location: `Offshore / Moscow IP`, PIN: `1234`.
   - **Result**: Blocked immediately. Card frozen.
4. **Brute-Force PIN Lockout**:
   - Enter incorrect PIN `9999` 3 times.
   - **Result**: Card locked immediately, SMS dispatched.
5. **Interactive Chatbot**:
   - Open chatbot on bottom right. Ask: *"Why was my last payment flagged?"* or *"Block my card"*.
6. **Admin Operations**:
   - Log in as `admin` / `admin123`.
   - Review KPI charts, inspect Fraud Alerts desk, view SMS gateway delivery audit, and test custom transaction vectors in the **Live ML Model Sandbox**.
