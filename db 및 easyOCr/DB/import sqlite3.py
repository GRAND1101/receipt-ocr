import sqlite3

# DB 연결 (없으면 자동 생성됨)
conn = sqlite3.connect("database.db")

# 커서 생성
cursor = conn.cursor()

# 테이블 생성
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    name TEXT
)
""")

# 데이터 삽입
cursor.execute("INSERT INTO users (email, name) VALUES (?, ?)", 
               ("test@example.com", "홍길동"))

# 데이터 조회
cursor.execute("SELECT * FROM users")
for row in cursor.fetchall():
    print(row)

# 저장 및 종료
conn.commit()
conn.close()
