# 베이스 이미지
FROM python:3.10-slim

# 시스템 패키지 설치 (Tesseract + OpenCV 의존성 포함)
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-kor \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1-mesa-glx && \
    rm -rf /var/lib/apt/lists/*

# 작업 디렉토리 설정
WORKDIR /app

# 코드 복사
COPY . /app

# 파이썬 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# 포트 설정
EXPOSE 8080

# 앱 실행 (Flask 앱을 Gunicorn으로 실행)
CMD ["gunicorn", "app:app", "--bind", "0.0.0.0:8080"]
