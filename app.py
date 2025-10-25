from flask import Flask, redirect, url_for, request, jsonify
from authlib.integrations.flask_client import OAuth
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
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

# ✅ DB 경로
DB_PATH = 'user_data.db'

# ✅ store_learning.json 절대경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORE_LEARNING_PATH = os.path.join(BASE_DIR, "store_learning.json")

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

        # ✅ deleted_at 컬럼이 없으면 추가 (소프트 삭제용)
        c.execute("PRAGMA table_info(transactions)")
        cols = [row[1] for row in c.fetchall()]
        if 'deleted_at' not in cols:
            c.execute("ALTER TABLE transactions ADD COLUMN deleted_at TEXT")

init_db()

# ✅ OCR 전처리
def preprocess_for_ocr(image_bytes):
    file_bytes = np.asarray(bytearray(image_bytes), dtype=np.uint8)
    img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    thresh = cv2.adaptiveThreshold(resized, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, 31, 15)
    return Image.fromarray(thresh)

# ✅ ROI OCR (상단 브랜드 추정)
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

# ✅ ROI OCR (하단 금액 추정)
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

# ✅ 환경 설정
load_dotenv()
UI_PATH = os.path.join(os.path.dirname(__file__), 'webapp-ui')

app = Flask(__name__, static_folder=UI_PATH, static_url_path='')
CORS(app, supports_credentials=True)
app.secret_key = os.getenv("SECRET_KEY") or "dev-secret-change-me"

# ✅ Windows일 때만 Tesseract 경로 지정 (Render는 Linux)
if os.name == 'nt':
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    os.environ['TESSDATA_PREFIX'] = r'C:\Program Files\Tesseract-OCR\tessdata'

# ✅ OAuth 설정
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# ✅ 로그인 매니저
login_manager = LoginManager()
login_manager.init_app(app)

# ✅ Flask-Login 요구 인터페이스를 직접 구현 (UserMixin 제거)
class AppUser:
    def __init__(self, id_, name, email):
        self.id = str(id_)
        self.name = name
        self.email = email
    @property
    def is_authenticated(self): return True
    @property
    def is_active(self): return True
    @property
    def is_anonymous(self): return False
    def get_id(self): return self.id

# 메모리 내 사용자 캐시
users = {}

@login_manager.user_loader
def load_user(user_id: str):
    return users.get(str(user_id))

@app.route('/')
def index():
    return open(os.path.join(app.static_folder, 'index.html'), encoding='utf-8').read()

@app.route('/login')
def login():
    # Render(HTTPS)에서 외부 콜백 URL 생성
    return google.authorize_redirect(url_for('callback', _external=True, _scheme='https'))

@app.route('/login/callback')
def callback():
    token = google.authorize_access_token()
    user_info = google.get('https://openidconnect.googleapis.com/v1/userinfo').json()
    user = AppUser(user_info['sub'], user_info['name'], user_info['email'])
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

# ✅ OCR 처리
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

    # ✅ DB 저장 (ocr_store에 fallback 적용)
    ocr_original_value = roi_brand if roi_brand else parsed_result.get("가맹점")
with closing(sqlite3.connect(DB_PATH)) as conn, conn:
    c = conn.cursor()
    cur = c.execute('''
        INSERT INTO transactions (user_id, store, amount, date, category, ocr_store, deleted_at)
        VALUES (?, ?, ?, ?, ?, ?, NULL)
    ''', (current_user.id,
          parsed_result.get("가맹점"),
          parsed_result.get("총금액"),
          date_value,
          parsed_result.get("카테고리"),
          ocr_original_value))
    tx_id = cur.lastrowid  # ✅ 새 레코드 ID

return jsonify({
    "status": "success",
    "transaction_id": tx_id,          # ✅ 추가
    "receipt": parsed_result,
    "raw_text": ocr_text,
    "roi_brand": roi_brand
})

# ✅ 거래 내역 (삭제 제외)
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

# ✅ 예산 API
@app.route('/api/budget', methods=['GET', 'POST'])
@login_required
def user_budget():
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        if request.method == 'POST':
            new_budget = request.json.get("budget")
            if not isinstance(new_budget, int) or new_budget <= 0:
                return jsonify({"error": "Invalid"}), 400
            c.execute('INSERT OR REPLACE INTO user_budget (user_id, budget) VALUES (?, ?)',
                      (current_user.id, new_budget))
            return jsonify({"status": "success", "budget": new_budget})
        c.execute('SELECT budget FROM user_budget WHERE user_id=?', (current_user.id,))
        row = c.fetchone()
    return jsonify({"budget": int(row[0]) if row else None})

# ✅ 통계 API (삭제 제외)
@app.route('/api/stats', methods=['GET'])
@login_required
def get_stats():
    with closing(sqlite3.connect(DB_PATH)) as conn:
        c = conn.cursor()

        month = request.args.get("month")  # ?month=YYYY-MM

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

        # ✅ 월별 데이터 (삭제 제외)
        c.execute("""
            SELECT SUBSTR(date, 1, 7), COALESCE(SUM(amount),0)
            FROM transactions
            WHERE user_id=? AND deleted_at IS NULL
            GROUP BY 1
        """, (current_user.id,))
        monthly_data = {str(k) if k else "unknown": int(v) for k, v in c.fetchall()}

        # ✅ 예산
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

# ✅ 인라인 수정 (PATCH) — 삭제된 항목은 수정 불가
@app.route('/api/correct-transaction/<int:transaction_id>', methods=['PATCH'])
@login_required
def correct_transaction(transaction_id):
    data = request.get_json()
    field = data.get("field")
    value = data.get("value")
    ocr_original = data.get("ocr_original") or value  # ✅ fallback 적용

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

            # ✅ OCR 학습 데이터 업데이트
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

# ✅ 삭제 API (소프트 삭제 기본, 하드 삭제 옵션)
@app.route('/api/transactions/<int:transaction_id>', methods=['DELETE'])
@login_required
def delete_transaction(transaction_id):
    hard = request.args.get('hard') == '1'
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        # 존재/소유 확인
        c.execute('SELECT id FROM transactions WHERE user_id=? AND id=?', (current_user.id, transaction_id))
        if not c.fetchone():
            return jsonify({"error": "Transaction not found"}), 404

        if hard:
            c.execute('DELETE FROM transactions WHERE user_id=? AND id=?', (current_user.id, transaction_id))
            return jsonify({"status": "deleted_hard", "id": transaction_id})

        # 소프트 삭제
        c.execute("""
            UPDATE transactions
            SET deleted_at = datetime('now')
            WHERE user_id=? AND id=? AND deleted_at IS NULL
        """, (current_user.id, transaction_id))
        return jsonify({"status": "deleted_soft", "id": transaction_id})

# ✅ 복원 API (소프트 삭제 되돌리기)
@app.route('/api/transactions/<int:transaction_id>/restore', methods=['POST'])
@login_required
def restore_transaction(transaction_id):
    with closing(sqlite3.connect(DB_PATH)) as conn, conn:
        c = conn.cursor()
        # 삭제된 본인 항목만 복원
        c.execute('SELECT id FROM transactions WHERE user_id=? AND id=? AND deleted_at IS NOT NULL',
                  (current_user.id, transaction_id))
        if not c.fetchone():
            return jsonify({"error": "Nothing to restore"}), 404
        c.execute('UPDATE transactions SET deleted_at=NULL WHERE user_id=? AND id=?',
                  (current_user.id, transaction_id))
    return jsonify({"status": "restored", "id": transaction_id})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))  # Render는 PORT 환경변수 사용
    app.run(host='0.0.0.0', port=port)

