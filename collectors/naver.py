"""
네이버 스마트스토어 수집기
"""
import asyncio
import json
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode
import aiohttp

from .base import BaseCollector, ProductInfo, ProductOption

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from config import NaverConfig


class NaverSmartStoreCollector(BaseCollector):
    """네이버 스마트스토어 상품 수집기"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.naver_config = NaverConfig()
        self.store_name = ""
        self.store_type = "brand"  # brand or smartstore

    def parse_url(self, url: str) -> Dict[str, Any]:
        """
        네이버 스마트스토어 URL 파싱

        Args:
            url: 네이버 스토어 URL

        Returns:
            파싱된 정보 (store_name, category_id, page 등)
        """
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        # 스토어 유형 판별
        if 'brand.naver.com' in parsed.netloc:
            self.store_type = "brand"
        else:
            self.store_type = "smartstore"

        # 스토어명, 카테고리 ID 추출
        path_parts = parsed.path.strip('/').split('/')
        store_name = path_parts[0] if path_parts else ""
        category_id = None

        if 'category' in path_parts:
            idx = path_parts.index('category')
            if idx + 1 < len(path_parts):
                category_id = path_parts[idx + 1]

        self.store_name = store_name

        return {
            "store_name": store_name,
            "store_type": self.store_type,
            "category_id": category_id,
            "page": int(query.get("cp", query.get("page", [1]))[0]),
        }

    # DOM에서 상품 추출하는 JavaScript
    JS_EXTRACT_PRODUCTS = """
    () => {
        const products = [];
        const links = document.querySelectorAll('a[href*="/products/"]');
        const seen = new Set();

        for (const link of links) {
            const href = link.href || '';
            const match = href.match(/\\/products\\/(\\d+)/);
            if (!match || seen.has(match[1])) continue;
            seen.add(match[1]);

            const card = link.closest('li') || link.parentElement;
            if (!card) continue;

            // 상품명
            const nameEl = card.querySelector('strong, [class*="name" i], [class*="title" i]');
            const name = nameEl ? nameEl.textContent.trim() : '';

            // 가격 추출
            const allText = card.textContent;
            const priceMatches = allText.match(/[0-9,]+원/g) || [];
            const prices = priceMatches.map(p => parseInt(p.replace(/[^0-9]/g, '')));

            // 이미지
            const img = card.querySelector('img');
            const imgUrl = img ? (img.src || '') : '';

            if (name) {
                products.push({
                    id: match[1],
                    name: name,
                    salePrice: prices[0] || 0,
                    price: prices[1] || prices[0] || 0,
                    imgUrl: imgUrl
                });
            }
        }
        return products;
    }
    """

    async def collect_category(self, url: str, start_page: int = 1, end_page: int = None) -> List[ProductInfo]:
        """카테고리 페이지에서 상품 목록 수집 (페이지 1: SSR 데이터, 페이지 2+: 버튼 클릭 + DOM 추출)"""
        products = []
        current_page = start_page
        has_next = True

        # URL 파싱 및 원본 URL 저장
        self.state.url = url
        url_info = self.parse_url(url)
        self.log(f"스토어: {url_info['store_name']} ({url_info['store_type']})")
        self.log(f"카테고리 ID: {url_info['category_id']}")

        # 브라우저가 없으면 시작
        if not self.page:
            await self.setup_browser()

        # 최초 페이지 로드 (항상 페이지 1 URL로 시작)
        page_url = self._build_page_url(url, 1)
        try:
            await self.page.goto(page_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
        except Exception as e:
            self.logger.error(f"초기 페이지 로드 실패: {e}")
            return products

        # __PRELOADED_STATE__에서 총 상품수/페이지사이즈 정보 추출 (1회)
        total_count = 0
        page_size = 40
        try:
            html = await self.page.content()
            match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});?\s*</script>', html, re.DOTALL)
            if match:
                state_data = json.loads(match.group(1))
                category_data = state_data.get('category', {})
                for key in category_data:
                    if isinstance(category_data[key], dict):
                        sub_data = category_data[key]
                        if sub_data.get('simpleProducts'):
                            total_count = sub_data.get('totalCount', 0)
                            page_size = sub_data.get('pageSize', 40)
                            break
        except Exception as e:
            self.logger.debug(f"__PRELOADED_STATE__ 파싱 실패: {e}")

        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1
        self.state.total_pages = total_pages
        self.log(f"  전체: {total_count}개 상품, {total_pages}페이지 (페이지당 {page_size}개)")

        # start_page가 1이 아닌 경우, 해당 페이지로 이동
        if start_page > 1:
            navigated = await self._navigate_to_page(start_page)
            if not navigated:
                self.log(f"  ⚠️ 페이지 {start_page}로 이동 실패")
                return products

        while has_next:
            if self.should_stop():
                self.log("  ⚠️ 사용자에 의해 수집이 중지되었습니다.")
                break

            self.log(f"  📄 페이지 {current_page} 수집 중...")

            try:
                if current_page == 1 and start_page == 1:
                    # 페이지 1: __PRELOADED_STATE__에서 풍부한 데이터 추출
                    page_products = await self._extract_from_preloaded_state()
                else:
                    # 페이지 2+: DOM에서 상품 추출
                    page_products = await self._extract_from_dom()

                if not page_products:
                    self.log(f"  ⚠️ 페이지 {current_page}: 상품 없음")
                    break

                self.log(f"  ✓ 페이지 {current_page}: {len(page_products)}개 상품 발견")
                products.extend(page_products)

                # 페이지네이션 확인
                if end_page and current_page >= end_page:
                    has_next = False
                elif current_page >= total_pages:
                    has_next = False
                else:
                    # 다음 페이지로 이동 (버튼 클릭)
                    next_page = current_page + 1
                    navigated = await self._navigate_to_page(next_page)
                    if not navigated:
                        self.log(f"  ⚠️ 페이지 {next_page} 이동 실패")
                        break
                    current_page = next_page
                    self.state.current_page = current_page
                    await self.random_delay()

            except Exception as e:
                self.logger.error(f"페이지 {current_page} 수집 실패: {e}")
                break

        return products

    async def _extract_from_preloaded_state(self) -> List[ProductInfo]:
        """__PRELOADED_STATE__에서 상품 목록 추출 (페이지 1 전용, 풍부한 데이터)"""
        try:
            html = await self.page.content()
            match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});?\s*</script>', html, re.DOTALL)
            if not match:
                return []

            state_data = json.loads(match.group(1))
            category_data = state_data.get('category', {})

            items = []
            for key in category_data:
                if isinstance(category_data[key], dict):
                    sub_data = category_data[key]
                    simple_products = sub_data.get('simpleProducts', [])
                    if simple_products:
                        items = simple_products
                        break

            if not items:
                return []

            products = []
            for item in items:
                benefits = item.get('benefitsView', {})
                sale_price = benefits.get('discountedSalePrice', 0) or item.get('salePrice', 0)
                original_price = item.get('salePrice', 0)

                brand_info = item.get('naverShoppingSearchInfo', {})
                brand = brand_info.get('brandName', '')

                product_id = str(item.get('id', ''))
                if self.store_type == "brand":
                    product_url = f"https://brand.naver.com/{self.store_name}/products/{product_id}"
                else:
                    product_url = f"https://smartstore.naver.com/{self.store_name}/products/{product_id}"

                product = ProductInfo(
                    product_id=product_id,
                    product_name=item.get('name', ''),
                    brand=brand or self.store_name,
                    price=original_price,
                    sale_price=sale_price,
                    image_url=item.get('representativeImageUrl', ''),
                    url=product_url,
                    extra_info={
                        'product_no': item.get('productNo', ''),
                        'option_usable': item.get('optionUsable', False),
                        'review_count': item.get('reviewAmount', {}).get('totalReviewCount', 0),
                        'rating': item.get('reviewAmount', {}).get('averageReviewScore', 0),
                    }
                )
                products.append(product)

            return products
        except Exception as e:
            self.logger.error(f"__PRELOADED_STATE__ 추출 실패: {e}")
            return []

    async def _extract_from_dom(self) -> List[ProductInfo]:
        """DOM에서 상품 목록 추출 (페이지 2+ 전용)"""
        try:
            dom_products = await self.page.evaluate(self.JS_EXTRACT_PRODUCTS)
            if not dom_products:
                return []

            products = []
            for item in dom_products:
                product_id = str(item.get('id', ''))
                if self.store_type == "brand":
                    product_url = f"https://brand.naver.com/{self.store_name}/products/{product_id}"
                else:
                    product_url = f"https://smartstore.naver.com/{self.store_name}/products/{product_id}"

                product = ProductInfo(
                    product_id=product_id,
                    product_name=item.get('name', ''),
                    brand=self.store_name,
                    price=item.get('price', 0),
                    sale_price=item.get('salePrice', 0),
                    image_url=item.get('imgUrl', ''),
                    url=product_url,
                    extra_info={
                        'option_usable': False,  # 상세 페이지에서 확인
                    }
                )
                products.append(product)

            return products
        except Exception as e:
            self.logger.error(f"DOM 추출 실패: {e}")
            return []

    async def _navigate_to_page(self, target_page: int) -> bool:
        """URL 기반으로 특정 페이지로 이동"""
        try:
            page_url = self._build_page_url(self.state.url, target_page)
            await self.page.goto(page_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            return True
        except Exception as e:
            self.logger.error(f"페이지 {target_page} 이동 실패: {e}")
            return False

    def _build_page_url(self, base_url: str, page: int) -> str:
        """페이지 URL 생성"""
        parsed = urlparse(base_url)
        query = parse_qs(parsed.query)

        # 페이지 파라미터 설정
        query['cp'] = [str(page)]
        if 'st' not in query:
            query['st'] = ['POPULAR']
        if 'dt' not in query:
            query['dt'] = ['BIG_IMAGE']
        if 'size' not in query:
            query['size'] = ['40']

        query_str = '&'.join(f"{k}={v[0]}" for k, v in query.items())
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query_str}"

    async def collect_product_detail(self, product: ProductInfo) -> ProductInfo:
        """상품 상세 정보 수집 (브라우저 필요)"""
        product_id = product.product_id
        detail_url = product.url

        # API 응답 캡처 변수
        product_data = None
        content_data = None

        async def capture_product_response(response):
            nonlocal product_data, content_data
            try:
                url = response.url
                # /products/{id} 패턴 매칭 (withWindow 파라미터 포함)
                if f'/products/{product_id}' in url and ('withWindow' in url or url.endswith(f'/products/{product_id}')):
                    if response.status == 200:
                        try:
                            data = await response.json()
                            # optionCombinations가 있는 응답만 사용
                            if 'optionCombinations' in data or 'name' in data:
                                product_data = data
                                self.logger.debug(f"API 응답 캡처: {url[:80]}...")
                        except:
                            pass
                # 상세 설명 컨텐츠 API 캡처
                elif '/contents/' in url and response.status == 200:
                    try:
                        data = await response.json()
                        if 'renderContent' in data:
                            content_data = data
                            self.logger.debug(f"컨텐츠 API 캡처: {url[:80]}...")
                    except:
                        pass
            except Exception as e:
                self.logger.debug(f"응답 캡처 실패: {e}")

        self.page.on('response', capture_product_response)

        try:
            # domcontentloaded로 변경하여 빠른 로딩, 이후 API 응답 대기
            await self.page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)

            # API 응답 대기 (최대 10초)
            for _ in range(20):
                if product_data:
                    break
                await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.warning(f"페이지 로딩 중 오류: {e}")
            # 타임아웃이어도 API 응답이 캡처되었을 수 있으므로 추가 대기
            await asyncio.sleep(2)
        finally:
            self.page.remove_listener('response', capture_product_response)

        if product_data:
            # 원산지
            origin_info = product_data.get('originAreaInfo', {})
            product.extra_info['origin'] = origin_info.get('content', '') if origin_info else ''

            # viewAttributes (상품속성)
            view_attrs = product_data.get('viewAttributes', {})
            if view_attrs:
                product.extra_info['manufacturer'] = view_attrs.get('제조사', '')
                product.extra_info['model_name'] = view_attrs.get('모델명', '')
                product.extra_info['manufacture_date'] = view_attrs.get('제조일자', '')
                product.extra_info['product_status'] = view_attrs.get('상품상태', '')

            # productInfoProvidedNoticeView (상품정보제공고시)
            notice = product_data.get('productInfoProvidedNoticeView', {})
            basic = notice.get('basic', {}) if notice else {}
            if basic:
                product.extra_info['material'] = basic.get('제품의 주소재', '')
                product.extra_info['color_info'] = basic.get('색상', '')
                product.extra_info['made_by'] = basic.get('제조자(사)', '')
                product.extra_info['made_in'] = basic.get('제조국', '')

                # 치수 정보
                size_info = basic.get('치수', {})
                if isinstance(size_info, dict):
                    product.extra_info['foot_length'] = size_info.get('발길이', '')
                    product.extra_info['heel_height'] = size_info.get('굽높이', '')

            # detailAttributes (상세속성) - 카테고리별로 다름
            detail_attrs = product_data.get('detailAttributes', {})
            if detail_attrs:
                # 일반 속성
                for key, value in detail_attrs.items():
                    # 키를 영문으로 변환
                    eng_key = self._korean_key_to_english(key)
                    product.extra_info[eng_key] = value

            # 추가 이미지 수집 (갤러리 이미지)
            product_images = product_data.get('productImages', []) or product_data.get('galleryImages', [])
            if product_images:
                extra_images = []
                for img_data in product_images:
                    img_url = img_data.get('url', '')
                    if img_url:
                        extra_images.append(img_url)
                product.extra_info['extra_images'] = extra_images

        # 상세 설명 이미지 수집 (renderContent에서 추출)
        if content_data:
            render_content = content_data.get('renderContent', '')
            if render_content:
                # HTML에서 img 태그의 src 추출
                detail_images = re.findall(r'<img[^>]+src="([^"]+)"', render_content)
                # data:image 제외, http로 시작하는 URL만 필터링
                detail_images = [url for url in detail_images if url.startswith('http')]
                if detail_images:
                    product.extra_info['detail_images'] = detail_images
                    self.logger.debug(f"상세 이미지 {len(detail_images)}개 수집")

        # 옵션 수집 - optionCombinations에서 추출 (API 기반)
        if product_data and product.extra_info.get('option_usable', False):
            option_combinations = product_data.get('optionCombinations', [])
            if option_combinations:
                # options 필드에서 groupName으로 optionName1/optionName2가 색상인지 사이즈인지 판별
                options_meta = product_data.get('options', [])
                option_role_map = {}  # {1: 'color', 2: 'size'} 등
                option_group_names = {}  # {1: '사이즈', 2: 'COLOR'} 원본 그룹명 보존
                for idx, opt_meta in enumerate(options_meta):
                    group_name_raw = opt_meta.get('groupName', '') or ''
                    group_name = group_name_raw.lower()
                    option_num = idx + 1  # optionName1, optionName2, ...
                    option_group_names[option_num] = group_name_raw.strip()
                    if '색상' in group_name or 'color' in group_name or '컬러' in group_name:
                        option_role_map[option_num] = 'color'
                    elif '사이즈' in group_name or 'size' in group_name:
                        option_role_map[option_num] = 'size'
                    else:
                        option_role_map[option_num] = 'size'  # 기본값

                options = []
                for opt in option_combinations:
                    color = ''
                    size = ''
                    option_data = {}

                    # optionName1, optionName2 등을 role에 따라 배정
                    for num in range(1, 4):  # optionName1 ~ optionName3
                        value = opt.get(f'optionName{num}', '')
                        if not value:
                            continue
                        role = option_role_map.get(num, 'size')
                        if role == 'color':
                            color = value
                        else:
                            size = value

                        # 원본 이름-값 쌍 보존
                        orig_name = option_group_names.get(num, f'Option{num}')
                        option_data[orig_name] = value

                    # role_map이 비어있으면 (options 필드 없는 경우) 기본 매핑
                    if not option_role_map:
                        size = opt.get('optionName1', '')
                        color = opt.get('optionName2', '')
                        if size:
                            option_data['Option1'] = size
                        if color:
                            option_data['Option2'] = color

                    stock = opt.get('stockQuantity', 0)
                    additional_price = opt.get('price', 0)
                    is_sold_out = opt.get('soldOut', False) or opt.get('isSoldOut', False) or stock == 0

                    options.append(ProductOption(
                        color=color,
                        size=size,
                        additional_price=additional_price,
                        stock=stock,
                        sold_out=is_sold_out,
                        option_data=option_data,
                    ))

                # 사이즈 순 정렬 (숫자인 경우)
                options.sort(key=lambda x: int(x.size) if x.size.isdigit() else 0)
                product.options = options
                self.logger.debug(f"옵션 수집 (API): {len(options)}개")

        return product

    def _korean_key_to_english(self, korean_key: str) -> str:
        """한글 키를 영문 키로 변환"""
        key_map = {
            '최소사용인원': 'min_players',
            '최대사용인원': 'max_players',
            '사용연령': 'age_limit',
            '장르': 'genre',
            '소요시간': 'play_time',
            '발목높이': 'ankle_height',
            '굽높이': 'heel_height_detail',
            '주요소재(신발)': 'main_material',
            '부가기능': 'function',
            '솔': 'sole',
        }
        return key_map.get(korean_key, korean_key.replace(' ', '_').lower())

    async def collect_options(self, product: ProductInfo) -> List[ProductOption]:
        """상품 옵션 수집"""
        # 옵션이 없는 상품은 스킵
        if not product.extra_info.get('option_usable', False):
            return []

        # API에서 이미 수집된 옵션이 있으면 반환
        if product.options:
            return product.options

        # API 데이터가 없는 경우 DOM 폴백 (거의 사용되지 않음)
        options = []
        try:
            # 드롭다운 클릭 시도
            await asyncio.sleep(0.5)

            click_selectors = [
                'text="옵션 선택"',
                'text="옵션선택"',
                'text="사이즈 선택"',
                'text="사이즈선택"',
                'text="크기 선택"',
                'text="색상 선택"',
                '[class*="selectbox"]',
                '[class*="option-select"]',
            ]

            for selector in click_selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element and await element.is_visible():
                        await element.click()
                        await asyncio.sleep(1)
                        break
                except:
                    continue

            # DOM에서 옵션 추출
            options_data = await self.page.evaluate("""
                () => {
                    const options = [];
                    const seen = new Set();

                    // 모든 li, option 요소에서 옵션 찾기
                    const elements = document.querySelectorAll('li, [role="option"], [class*="option-item"]');

                    for (const el of elements) {
                        const text = el.textContent.trim();

                        // 옵션 패턴 확인 (숫자, 사이즈 문자 등)
                        if (text && text.length < 50 && !text.includes('선택')) {
                            // 추가금액 파싱
                            let additionalPrice = 0;
                            const priceMatch = text.match(/\\+(\\d+(?:,\\d+)?)원/);
                            if (priceMatch) {
                                additionalPrice = parseInt(priceMatch[1].replace(',', ''));
                            }

                            // 옵션값 추출 (추가금액 제거)
                            let optionValue = text.replace(/\\s*\\([^)]*\\)\\s*$/, '').trim();
                            optionValue = optionValue.replace(/\\s*\\+\\d+(?:,\\d+)?원\\s*$/, '').trim();

                            // 품절 체크
                            const isSoldOut = el.classList.contains('disabled') ||
                                             el.classList.contains('soldout') ||
                                             el.classList.contains('sold-out') ||
                                             el.hasAttribute('disabled') ||
                                             text.includes('품절');

                            if (optionValue && !seen.has(optionValue) &&
                                !optionValue.includes('원') &&
                                optionValue.length < 30) {
                                seen.add(optionValue);
                                options.push({
                                    value: optionValue,
                                    additionalPrice: additionalPrice,
                                    soldOut: isSoldOut
                                });
                            }
                        }
                    }

                    return options;
                }
            """)

            for opt_data in options_data:
                options.append(ProductOption(
                    color='',
                    size=opt_data.get('value', ''),
                    additional_price=opt_data.get('additionalPrice', 0),
                    stock=0 if opt_data.get('soldOut', False) else 100,
                    sold_out=opt_data.get('soldOut', False),
                ))

        except Exception as e:
            self.logger.debug(f"옵션 수집 실패 [{product.product_id}]: {e}")

        return options


def is_naver_store_url(url: str) -> bool:
    """네이버 스마트스토어 URL인지 확인"""
    parsed = urlparse(url)
    return 'brand.naver.com' in parsed.netloc or 'smartstore.naver.com' in parsed.netloc
