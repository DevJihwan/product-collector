"""
설정 파일
"""
import os
import sys
from pathlib import Path

# PyInstaller exe 실행 시 Playwright가 시스템에 설치된 브라우저를 사용하도록 설정
# '0'은 Playwright의 기본 전역 설치 경로를 사용하라는 의미
if getattr(sys, 'frozen', False):
    os.environ.setdefault('PLAYWRIGHT_BROWSERS_PATH', '0')

# 프로젝트 루트 디렉토리
# PyInstaller exe 실행 시 exe 위치 사용 (임시 폴더 문제 방지)
if getattr(sys, 'frozen', False):
    # PyInstaller로 빌드된 exe 실행 중
    BASE_DIR = Path(sys.executable).parent
else:
    # 일반 Python 스크립트 실행 중
    BASE_DIR = Path(__file__).parent

# 출력 디렉토리
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR = BASE_DIR / "logs"
DATA_DIR = BASE_DIR / "data"

# 디렉토리 생성
OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# 수집 설정
class CollectorConfig:
    # 요청 간격 (초)
    REQUEST_DELAY_MIN = 1.0
    REQUEST_DELAY_MAX = 2.0

    # 재시도 설정
    MAX_RETRIES = 3
    RETRY_DELAY = 5.0

    # 배치 크기
    BATCH_SIZE = 20

    # 타임아웃 (밀리초)
    PAGE_TIMEOUT = 30000
    API_TIMEOUT = 15000

    # 브라우저 설정
    HEADLESS = True  # True: 백그라운드, False: 브라우저 표시
    VIEWPORT_WIDTH = 1920
    VIEWPORT_HEIGHT = 1080

    # User Agent
    USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


# 무신사 설정
class MusinsaConfig:
    # 카테고리 API
    CATEGORY_API = "api.musinsa.com/api2/dp/v1/plp/goods"

    # 상품 정보 API
    PRODUCT_INFO_API = "goods-detail.musinsa.com/api2/goods/{goods_no}"
    PRODUCT_STAT_API = "goods-detail.musinsa.com/api2/goods/{goods_no}/stat"
    PRODUCT_OPTIONS_API = "goods-detail.musinsa.com/api2/goods/{goods_no}/options"

    # 상품 URL
    PRODUCT_URL = "https://www.musinsa.com/products/{goods_no}"

    # 페이지당 상품 수
    ITEMS_PER_PAGE = 60


# 네이버 스마트스토어 설정
class NaverConfig:
    # 페이지당 상품 수
    ITEMS_PER_PAGE = 80

    # 상품 URL 템플릿
    PRODUCT_URL = "https://brand.naver.com/{store}/products/{product_id}"
    SMARTSTORE_PRODUCT_URL = "https://smartstore.naver.com/{store}/products/{product_id}"


# 엑셀 출력 설정
class ExcelConfig:
    # 시트 이름
    SHEET_NAME = "상품목록"

    # 기본 재고 수량 (재고 정보 미제공 시)
    DEFAULT_STOCK = 100

    # 사이즈 국가 코드
    SIZE_COUNTRY_CODE = "KR"
