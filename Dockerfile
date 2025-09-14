# 베이스 이미지
FROM python:3.10-slim-bookworm

# 시스템 패키지 설치 (Tesseract + OpenCV 런타임 의존성)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-kor \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libgl1 \
 && rm -rf /var/lib/apt/lists/*

# 작업 디렉토리
WORKDIR /app

# (캐시 최적화) requirements.txt 먼저 복사 후 설치
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 앱 코드 복사
COPY . /app

# Render는 지정 포트 사용
EXPOSE 8080

# Tesseract 내부 스레드 제한 (메모리 폭주 방지)
ENV OMP_THREAD_LIMIT=1

# Gunicorn 실행 (타임아웃/스레드 튜닝 포함)
CMD ["bash", "-lc", "gunicorn app:app \
  --bind 0.0.0.0:${PORT:-8080} \
  --workers 1 \
  --threads 2 \
  --timeout 120 \
  --graceful-timeout 30 \
  --keep-alive 5"]
