from flask import Flask, redirect, url_for, request, jsonify, send_from_directory
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_cors import CORS
from dotenv import load_dotenv
import pytesseract
import os
import cv2
import numpy as np
from PIL import Image
import json
import datetime
import sqlite3
from contextlib import closing
from parser import parse_receipt_text

# ==========================
# 기본 설정/경로
# ==========================
DB_PATH = 'user_data.db'
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_LEARNING_PATH = os.path.join(BASE_DIR, "store_learning.json")
UI_PATH = os.path.join(BASE_DIR, 'webapp-ui')

# ==========================
# DB 초기화
# ==========================
def init_db():
    """기본 테이블 생성 + deleted_at 컬럼 자동 보강"""
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                store TEXT,
                amount INTEGER,
                date TEXT,
                category TEXT,
                ocr_store TEXT
                -- deleted_at 은 아래 보강 루틴에서 필요 시 추가
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS user_budget (
                user_id TEXT PRIMARY KEY,
                budget INTEGER
            )
        ''')
        # deleted_at 없으면 추가
        c.execute("PRAGMA table_info(transactions)")
        cols = [row[1] for row in c.fetchall()]
        if 'deleted_at' not in cols:
            c.execute("ALTER TABLE transactions ADD COLUMN deleted_at TEXT")

init_db()

# ==========================
# OCR 전처리/ROI
# ==========================
def preprocess_for_ocr(image_bytes):
    file_bytes = np.asarray(bytearray(image_bytes), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    thresh = cv2.adaptiveThreshold(resized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 15)
    return Image.fromarray(thresh)

def extract_top_brand(img):
    h, w = img.shape[:2]
    roi = img[0:int(h * 0.2), 0:w]
    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    roi_gray = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    roi_text = pytesseract.image_to_string(
        roi_gray, lang='kor+eng',
        config='--oem 3 --psm 7 -c tessedit_char_whitelist="가-힣A-Za-z0-9"'
    ).strip()
    return roi_text

def extract_bottom_amount(img):
    h, w = img.shape[:2]
    roi = img[int(h * 0.7):h, 0:w]
    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    roi_gray = cv2.threshold(roi_gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    text = pytesseract.image_to_string(
        roi_gray, lang='kor+eng',
        config='--oem 3 --psm 6 -c tessedit_char_whitelist="0123456789,"'
    )
    nums = [int(n.replace(",", "")) for n in text.split() if n.replace(",", "").isdigit()]
    return max(nums) if nums else None

# ==========================
# 앱/보안/로그인
# ==========================
load_dotenv()

app = Flask(__name__, static_folder=UI_PATH, static_url_path='')
CORS(app, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY") or "change-me"

# Windows에서만 경로 지정 (Render 리눅스에서는 미적용)
if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'

oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

login_manager = LoginManager()
login_manager.init_app(app)  # ✅ 변경: 데코레이터가 아니라 메서드 호출
login_manager.login_view = "login"

class User(UserMixin):
    def __init__(self, id_, name, email):
        self.id = id_
        self.name = name
        self.email = email

users = {}

@login_manager.user_loader
def load_user(user_id):
    return users.get(user_id)

# ==========================
# 정적/인증 라우트
# ==========================
@app.route('/')
def index():
    # 안전한 정적 파일 제공
    return send_from_directory(app.static_folder, 'index.html', max_age=0)

@app.route('/login')
def login():
    # Render는 HTTPS, 로컬은 HTTP – _scheme 자동 판단을 위해 제거
    return google.authorize_redirect(url_for('callback', _external=True))

@app.route('/login/callback')
def callback():
    token = google.authorize_access_token()
    user_info = google.get('https://openidconnect.googleapis.com/v1/userinfo').json()
    user = User(user_info['sub'], user_info.get('name', ''), user_info.get('email', ''))
    users[user.id] = user
    login_user(user)
    return redirect('/')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect('/')

@app.route('/user-info')
def user_info():
    if current_user.is_authenticated:
        return jsonify({"logged_in": True, "name": current_user.name, "email": current_user.email})
    return jsonify({"logged_in": False})

# ==========================
# OCR 업로드
# ==========================
@app.route('/ocr', methods=['POST'])
@login_required
def ocr_endpoint():
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    image_file = request.files['image']
    image_bytes = image_file.read()
    img = cv2.imdecode(np.asarray(bytearray(image_bytes), dtype=np.uint8), cv2.IMREAD_COLOR)

    roi_brand = extract_top_brand(img)
    roi_amount = extract_bottom_amount(img)

    processed_image = preprocess_for_ocr(image_bytes)
    ocr_text = pytesseract.image_to_string(processed_image, lang='kor+eng', config='--psm 6')
    ocr_lines = ocr_text.splitlines()
    parsed_result, _, _ = parse_receipt_text(ocr_lines, roi_brand)

    if not parsed_result.get("총금액") and roi_amount:
        parsed_result["총금액"] = roi_amount

    date_value = parsed_result.get("날짜") or datetime.datetime.now().strftime('%Y-%m-%d')

    # DB 저장 (ocr_store에 fallback 적용)
    ocr_original_value = roi_brand if roi_brand else parsed_result.get("가맹점")
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute('''
            INSERT INTO transactions (user_id, store, amount, date, category, ocr_store, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, NULL)
        ''', (current_user.id,
              parsed_result.get("가맹점"),
              parsed_result.get("총금액"),
              date_value,
              parsed_result.get("카테고리"),
              ocr_original_value))
    return jsonify({"status": "success", "receipt": parsed_result, "raw_text": ocr_text, "roi_brand": roi_brand})

# ==========================
# 데이터 조회/통계/예산
# ==========================
@app.route('/api/user-data', methods=['GET'])
@login_required
def get_user_data():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        c = conn.cursor()
        c.execute('''
            SELECT id, store, amount, date, category, ocr_store
            FROM transactions
            WHERE user_id=? AND deleted_at IS NULL
            ORDER BY id DESC
        ''', (current_user.id,))
        rows = c.fetchall()
    return jsonify([{
        "id": r[0], "store": r[1], "amount": r[2],
        "date": r[3], "category": r[4], "ocr_store": r[5]
    } for r in rows])

@app.route('/api/budget', methods=['GET', 'POST'])
@login_required
def user_budget():
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        if request.method == 'POST':
            data = request.get_json(silent=True) or {}
            new_budget = data.get("budget")
            if not isinstance(new_budget, int) or new_budget <= 0:
                return jsonify({"error": "Invalid"}), 400
            c.execute('INSERT OR REPLACE INTO user_budget (user_id, budget) VALUES (?, ?)',
                      (current_user.id, new_budget))
            return jsonify({"status": "success", "budget": new_budget})
        c.execute('SELECT budget FROM user_budget WHERE user_id=?', (current_user.id,))
        row = c.fetchone()
    return jsonify({"budget": int(row[0]) if row else None})

@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        c = conn.cursor()
        month = request.args.get("month")  # YYYY-MM

        if month:
            c.execute("""
                SELECT COALESCE(SUM(amount),0), COUNT(*)
                FROM transactions
                WHERE user_id=? AND deleted_at IS NULL AND strftime('%Y-%m', date) = ?
            """, (current_user.id, month))
            total_spent, count = c.fetchone()

            c.execute("""
                SELECT category, COALESCE(SUM(amount),0)
                FROM transactions
                WHERE user_id=? AND deleted_at IS NULL AND strftime('%Y-%m', date) = ?
                GROUP BY category
            """, (current_user.id, month))
            category_data = {str(k) if k else "기타": int(v) for k, v in c.fetchall()}
        else:
            c.execute("""
                SELECT COALESCE(SUM(amount),0), COUNT(*)
                FROM transactions
                WHERE user_id=? AND deleted_at IS NULL
            """, (current_user.id,))
            total_spent, count = c.fetchone()

            c.execute("""
                SELECT category, COALESCE(SUM(amount),0)
                FROM transactions
                WHERE user_id=? AND deleted_at IS NULL
                GROUP BY category
            """, (current_user.id,))
            category_data = {str(k) if k else "기타": int(v) for k, v in c.fetchall()}

        # 월별 집계 (항상 전체)
        c.execute("""
            SELECT SUBSTR(date, 1, 7), COALESCE(SUM(amount),0)
            FROM transactions
            WHERE user_id=? AND deleted_at IS NULL
            GROUP BY 1
        """, (current_user.id,))
        monthly_data = {str(k) if k else "unknown": int(v) for k, v in c.fetchall()}

        # 예산
        c.execute('SELECT budget FROM user_budget WHERE user_id=?', (current_user.id,))
        row = c.fetchone()
        budget = int(row[0]) if row else 0

    return jsonify({
        "total_spent": int(total_spent),
        "transaction_count": int(count),
        "monthly_budget": budget,
        "remaining_budget": (budget - int(total_spent)) if budget else 0,
        "category_stats": category_data,
        "monthly_stats": monthly_data
    })

# ==========================
# 인라인 수정 (PATCH)
# ==========================
@app.route('/api/correct-transaction/<int:transaction_id>', methods=['PATCH'])
@login_required
def correct_transaction(transaction_id):
    data = request.get_json(silent=True) or {}
    field = data.get("field")
    value = data.get("value")
    ocr_original = data.get("ocr_original") or value  # fallback

    if not field or value is None:
        return jsonify({"error": "Invalid input"}), 400

    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute('SELECT id FROM transactions WHERE user_id=? AND id=? AND deleted_at IS NULL',
                  (current_user.id, transaction_id))
        if not c.fetchone():
            return jsonify({"error": "Transaction not found or deleted"}), 404

        if field == "store":
            c.execute('UPDATE transactions SET store=? WHERE id=?', (value, transaction_id))
            # OCR 학습 매핑 저장
            if ocr_original and ocr_original != value and len(ocr_original) < 100:
                if not os.path.exists(STORE_LEARNING_PATH):
                    with open(STORE_LEARNING_PATH, "w", encoding="utf-8") as f:
                        json.dump({}, f, ensure_ascii=False, indent=2)
                try:
                    with open(STORE_LEARNING_PATH, "r", encoding="utf-8") as f:
                        mapping = json.load(f)
                except json.JSONDecodeError:
                    mapping = {}
                mapping[ocr_original] = value
                with open(STORE_LEARNING_PATH, "w", encoding="utf-8") as f:
                    json.dump(mapping, f, ensure_ascii=False, indent=2)
                print(f"✔ OCR 학습 데이터 저장: {ocr_original} → {value}")

        elif field == "amount":
            c.execute('UPDATE transactions SET amount=? WHERE id=?', (int(value), transaction_id))
        elif field == "date":
            c.execute('UPDATE transactions SET date=? WHERE id=?', (value, transaction_id))
        elif field == "category":
            c.execute('UPDATE transactions SET category=? WHERE id=?', (value, transaction_id))
        else:
            return jsonify({"error": "Unsupported field"}), 400

    return jsonify({"status": "success", "updated": {field: value}}), 200

# ==========================
# 삭제/복원 API
# ==========================
@app.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
@login_required
def delete_transaction(transaction_id):
    hard = request.args.get('hard') == '1'
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute('SELECT id FROM transactions WHERE user_id=? AND id=?', (current_user.id, transaction_id))
        if not c.fetchone():
            return jsonify({"error": "Transaction not found"}), 404

        if hard:
            c.execute('DELETE FROM transactions WHERE user_id=? AND id=?', (current_user.id, transaction_id))
            return jsonify({"status": "deleted_hard", "id": transaction_id})

        c.execute("""
            UPDATE transactions
            SET deleted_at = datetime('now')
            WHERE user_id=? AND id=? AND deleted_at IS NULL
        """, (current_user.id, transaction_id))
        return jsonify({"status": "deleted_soft", "id": transaction_id})

@app.route('/api/transactions/<int:transaction_id>/restore', methods=['POST'])
@login_required
def restore_transaction(transaction_id):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute('SELECT id FROM transactions WHERE user_id=? AND id=? AND deleted_at IS NOT NULL',
                  (current_user.id, transaction_id))
        if not c.fetchone():
            return jsonify({"error": "Nothing to restore"}), 404
        c.execute('UPDATE transactions SET deleted_at=NULL WHERE user_id=? AND id=?',
                  (current_user.id, transaction_id))
    return jsonify({"status": "restored", "id": transaction_id})

# ✅ 폴백용 삭제 엔드포인트 (프론트에서 POST /api/delete 지원)
@app.route('/api/delete', methods=['POST'])
@login_required
def delete_transaction_legacy():
    data = request.get_json(silent=True) or {}
    txn_id = data.get("id")
    if not txn_id:
        return jsonify({"status": "error", "error": "missing id"}), 400
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        c.execute('SELECT id FROM transactions WHERE user_id=? AND id=?', (current_user.id, txn_id))
        if not c.fetchone():
            return jsonify({"status": "error", "error": "not found"}), 404
        c.execute("""
            UPDATE transactions
            SET deleted_at = datetime('now')
            WHERE user_id=? AND id=? AND deleted_at IS NULL
        """, (current_user.id, txn_id))
    return jsonify({"status": "success", "deleted_id": txn_id})

# ==========================
# 엔트리포인트
# ==========================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))  # Render는 PORT 사용
    # 개발 편의를 위해 debug는 필요 시만
    app.run(host='0.0.0.0', port=port)
