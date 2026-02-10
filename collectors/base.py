"""
기본 수집기 클래스
"""
import asyncio
import json
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

import sys
sys.path.append(str(Path(__file__).parent.parent))

from config import CollectorConfig, OUTPUT_DIR, LOGS_DIR
from utils.logger import setup_logger, ProgressLogger


@dataclass
class ProductOption:
    """상품 옵션 데이터"""
    color: str = ""
    size: str = ""
    additional_price: int = 0
    stock: int = 100
    sold_out: bool = False
    # 원본 옵션 데이터 (이름:값 쌍, 순서 보존)
    option_data: Dict[str, str] = field(default_factory=dict)
    # 옵션별 이미지 URL (다이소 등 옵션마다 이미지가 다른 경우)
    image_url: str = ""
    # 옵션별 추가 이미지 (갤러리)
    extra_images: List[str] = field(default_factory=list)
    # 옵션별 상세 이미지
    detail_images: List[str] = field(default_factory=list)


@dataclass
class ProductInfo:
    """상품 정보 데이터"""
    # 기본 정보
    product_id: str = ""
    product_name: str = ""
    brand: str = ""
    price: int = 0
    sale_price: int = 0
    image_url: str = ""
    url: str = ""

    # 옵션
    options: List[ProductOption] = field(default_factory=list)

    # 상품정보 (사이트별로 다름)
    extra_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectionState:
    """수집 상태 (중단/재개용)"""
    url: str = ""
    total_pages: int = 0
    current_page: int = 0
    collected_products: List[Dict] = field(default_factory=list)
    failed_products: List[Dict] = field(default_factory=list)
    start_time: str = ""
    last_update: str = ""

    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "total_pages": self.total_pages,
            "current_page": self.current_page,
            "collected_count": len(self.collected_products),
            "failed_count": len(self.failed_products),
            "start_time": self.start_time,
            "last_update": self.last_update,
        }


class BaseCollector(ABC):
    """기본 수집기 추상 클래스"""

    def __init__(self, headless: bool = True):
        """
        초기화

        Args:
            headless: 브라우저 헤드리스 모드
        """
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

        self.logger = setup_logger(self.__class__.__name__, LOGS_DIR)
        self.state = CollectionState()

        # 설정
        self.config = CollectorConfig()

        # 외부 로그 콜백 (GUI 앱에서 사용)
        self.log_callback = None
        # 중지 체크 콜백 (GUI 앱에서 사용)
        self.stop_check = None

    def log(self, message: str):
        """로그 메시지 출력 (파일 + 콜백)"""
        self.logger.info(message)
        if self.log_callback:
            self.log_callback(message)

    def should_stop(self) -> bool:
        """중지 요청 여부 확인"""
        if self.stop_check:
            return self.stop_check()
        return False

    async def setup_browser(self):
        """브라우저 설정"""
        self.logger.info("브라우저 시작 중...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            user_agent=self.config.USER_AGENT,
            viewport={
                "width": self.config.VIEWPORT_WIDTH,
                "height": self.config.VIEWPORT_HEIGHT
            }
        )
        self.page = await self.context.new_page()
        self.logger.info("브라우저 준비 완료")

    async def close_browser(self):
        """브라우저 종료"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.logger.info("브라우저 종료")

    async def random_delay(self, min_sec: float = None, max_sec: float = None):
        """랜덤 딜레이"""
        min_sec = min_sec or self.config.REQUEST_DELAY_MIN
        max_sec = max_sec or self.config.REQUEST_DELAY_MAX
        delay = random.uniform(min_sec, max_sec)
        await asyncio.sleep(delay)

    async def retry_on_error(self, func, *args, max_retries: int = None, **kwargs):
        """에러 시 재시도"""
        max_retries = max_retries or self.config.MAX_RETRIES

        for attempt in range(max_retries):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                self.logger.warning(f"시도 {attempt + 1}/{max_retries} 실패: {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(self.config.RETRY_DELAY * (attempt + 1))
                else:
                    raise

    def save_state(self, file_path: Path = None):
        """수집 상태 저장 (중단/재개용)"""
        if not file_path:
            file_path = OUTPUT_DIR / "collection_state.json"

        self.state.last_update = datetime.now().isoformat()

        state_data = {
            "state": self.state.to_dict(),
            "collected_products": self.state.collected_products,
            "failed_products": self.state.failed_products,
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(state_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"상태 저장: {file_path}")

    def load_state(self, file_path: Path = None) -> bool:
        """수집 상태 로드"""
        if not file_path:
            file_path = OUTPUT_DIR / "collection_state.json"

        if not file_path.exists():
            return False

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                state_data = json.load(f)

            state_dict = state_data.get("state", {})
            self.state.url = state_dict.get("url", "")
            self.state.total_pages = state_dict.get("total_pages", 0)
            self.state.current_page = state_dict.get("current_page", 0)
            self.state.start_time = state_dict.get("start_time", "")
            self.state.collected_products = state_data.get("collected_products", [])
            self.state.failed_products = state_data.get("failed_products", [])

            self.logger.info(f"상태 로드: 페이지 {self.state.current_page}/{self.state.total_pages}, "
                           f"수집 {len(self.state.collected_products)}개")
            return True
        except Exception as e:
            self.logger.error(f"상태 로드 실패: {e}")
            return False

    @abstractmethod
    async def collect_category(self, url: str, start_page: int = 1, end_page: int = None) -> List[ProductInfo]:
        """
        카테고리 페이지에서 상품 수집

        Args:
            url: 카테고리 페이지 URL
            start_page: 시작 페이지
            end_page: 종료 페이지 (None이면 전체)

        Returns:
            수집된 상품 목록
        """
        pass

    @abstractmethod
    async def collect_product_detail(self, product: ProductInfo) -> ProductInfo:
        """
        상품 상세 정보 수집

        Args:
            product: 기본 상품 정보

        Returns:
            상세 정보가 추가된 상품
        """
        pass

    @abstractmethod
    async def collect_options(self, product: ProductInfo) -> List[ProductOption]:
        """
        상품 옵션 수집

        Args:
            product: 상품 정보

        Returns:
            옵션 목록
        """
        pass

    async def collect_all(self, url: str, start_page: int = 1, end_page: int = None,
                         resume: bool = False) -> List[ProductInfo]:
        """
        전체 수집 프로세스

        Args:
            url: 카테고리 페이지 URL
            start_page: 시작 페이지
            end_page: 종료 페이지
            resume: 이전 상태에서 재개

        Returns:
            수집된 상품 목록
        """
        # 재개 모드
        if resume and self.load_state():
            start_page = self.state.current_page + 1
            self.logger.info(f"이전 상태에서 재개: 페이지 {start_page}부터")
        else:
            self.state = CollectionState()
            self.state.url = url
            self.state.start_time = datetime.now().isoformat()

        try:
            await self.setup_browser()

            # 1. 카테고리에서 상품 목록 수집
            self.logger.info("=" * 60)
            self.logger.info("1단계: 카테고리 페이지에서 상품 목록 수집")
            self.logger.info("=" * 60)

            products = await self.collect_category(url, start_page, end_page)
            self.logger.info(f"상품 목록 수집 완료: {len(products)}개")

            # 2. 상세 정보 + 옵션 수집
            self.logger.info("=" * 60)
            self.logger.info("2단계: 상품 상세 정보 및 옵션 수집")
            self.logger.info("=" * 60)

            progress = ProgressLogger(len(products), prefix="상세수집 ", logger=self.logger)

            for i, product in enumerate(products):
                try:
                    # 상세 정보 수집
                    product = await self.collect_product_detail(product)

                    # 옵션 수집
                    product.options = await self.collect_options(product)

                    # 상태 저장 (배치 단위)
                    self.state.collected_products.append(self._product_to_dict(product))

                    if (i + 1) % self.config.BATCH_SIZE == 0:
                        self.save_state()

                    progress.update(f"{product.product_name[:30]}... 옵션 {len(product.options)}개")

                except Exception as e:
                    self.logger.error(f"상품 수집 실패 [{product.product_id}]: {e}")
                    self.state.failed_products.append({
                        "product_id": product.product_id,
                        "error": str(e)
                    })

                await self.random_delay()

            progress.finish()

            # 최종 상태 저장
            self.save_state()

            self.logger.info("=" * 60)
            self.logger.info("수집 완료")
            self.logger.info(f"  성공: {len(self.state.collected_products)}개")
            self.logger.info(f"  실패: {len(self.state.failed_products)}개")
            self.logger.info("=" * 60)

            return products

        finally:
            await self.close_browser()

    def _product_to_dict(self, product: ProductInfo) -> Dict:
        """ProductInfo를 딕셔너리로 변환"""
        return {
            "product_id": product.product_id,
            "product_name": product.product_name,
            "brand": product.brand,
            "price": product.price,
            "sale_price": product.sale_price,
            "image_url": product.image_url,
            "url": product.url,
            "options": [
                {
                    "color": opt.color,
                    "size": opt.size,
                    "additional_price": opt.additional_price,
                    "stock": opt.stock,
                    "sold_out": opt.sold_out,
                    "option_data": opt.option_data,
                }
                for opt in product.options
            ],
            "extra_info": product.extra_info,
        }
