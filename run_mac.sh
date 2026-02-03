#!/bin/bash

echo "============================================================"
echo "  무신사 / 네이버 스마트스토어 상품 데이터 수집 프로그램"
echo "============================================================"
echo

# Python 확인
if ! command -v python3 &> /dev/null; then
    echo "[오류] Python3이 설치되어 있지 않습니다."
    echo "Python 3.8 이상을 설치해주세요: https://www.python.org/downloads/"
    exit 1
fi

# 스크립트 디렉토리로 이동
cd "$(dirname "$0")"

# 의존성 설치 확인
echo "의존성 확인 중..."
if ! python3 -c "import customtkinter" &> /dev/null; then
    echo "의존성 설치 중..."
    pip3 install -r requirements.txt
    python3 -m playwright install chromium
fi

echo "프로그램을 시작합니다..."
echo

# GUI 앱 실행
python3 app.py
