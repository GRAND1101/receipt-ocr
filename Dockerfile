# 베이스 이미지
FROM python:3.10-slim-bookworm   # trixie 대신 bookworm 고정이 안전

# 시스템 패키지 설치 (Tesseract + OpenCV 런타임 의존성)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-kor \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \        # libxrender-dev -> libxrender1 (runtime)
    libgl1               # libgl1-mesa-glx -> libgl1
 && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리
WORKDIR /app

# (레이어 캐시 최적화) 의존성 먼저 복사/설치
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 나머지 코드 복사
COPY . /app

# Render는 지정 포트를 열어주므로 EXPOSE는 생략 가능하지만 적어도 무방
EXPOSE 8080

# Gunicorn 실행 — Render에서는 반드시 $PORT 사용
CMD ["bash", "-lc", "gunicorn app:app --bind 0.0.0.0:${PORT:-8080}"]
