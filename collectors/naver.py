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
        self.channel_id = None  # 카테고리 로드 시 캡처
        self.current_store_category = ""  # 현재 수집 중인 스토어 카테고리명
        self.page_size = None  # 서버 응답 pageSize (동적)

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

            // 가격 추출 (배송비 제외)
            // 카드 텍스트 패턴:
            //   비할인: [상품가, 배송비] (2개, 취소선 없음)
            //   할인:   [정가, 할인가, 배송비] (3개, 취소선 있음)
            // → 가격이 2개 이상이면 마지막은 배송비이므로 제외
            const allText = card.textContent;
            const priceMatches = allText.match(/[0-9,]+원/g) || [];
            const allPrices = priceMatches.map(p => parseInt(p.replace(/[^0-9]/g, '')));

            // 가격이 2개 이상이면 마지막 가격(배송비) 제외
            const prices = allPrices.length >= 2 ? allPrices.slice(0, -1) : allPrices;

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
        seen_ids = set()  # 중복 방지용 product_id 집합
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

        # channel_id 캡처용 리스너
        async def capture_channel_id(response):
            try:
                url_str = response.url
                m = re.search(r'/n/v2/channels/([^/]+)/', url_str)
                if m and not self.channel_id:
                    self.channel_id = m.group(1)
                    self.logger.debug(f"channel_id 캡처: {self.channel_id}")
            except Exception:
                pass

        self.page.on('response', capture_channel_id)

        # 최초 페이지 로드 (항상 페이지 1 URL로 시작)
        page_url = self._build_page_url(url, 1)
        try:
            await self.page.goto(page_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
        except Exception as e:
            self.logger.error(f"초기 페이지 로드 실패: {e}")
            self.page.remove_listener('response', capture_channel_id)
            return products

        self.page.remove_listener('response', capture_channel_id)

        # 1) HTML DOM에서 전체 상품수 + 페이지당 상품수 추출
        total_count = 0
        page_size = 0
        try:
            # DOM에서 전체 상품 건수 읽기 ("전체 2,000개", "총 500개" 등)
            total_count = await self.page.evaluate("""
                () => {
                    const body = document.body.innerText;
                    // "전체 N개", "총 N개", "N개의 상품" 등 패턴 매칭
                    const patterns = [
                        /전체\\s*([0-9,]+)\\s*개/,
                        /총\\s*([0-9,]+)\\s*개/,
                        /([0-9,]+)\\s*개의\\s*상품/,
                        /상품\\s*([0-9,]+)\\s*개/,
                    ];
                    for (const p of patterns) {
                        const m = body.match(p);
                        if (m) return parseInt(m[1].replace(/,/g, ''));
                    }
                    return 0;
                }
            """) or 0

            # 첫 페이지에 렌더링된 상품 수 = page_size
            first_page_count = await self.page.evaluate("""
                () => {
                    const links = document.querySelectorAll('a[href*="/products/"]');
                    const seen = new Set();
                    for (const link of links) {
                        const m = link.href.match(/\\/products\\/(\\d+)/);
                        if (m) seen.add(m[1]);
                    }
                    return seen.size;
                }
            """) or 0

            if first_page_count > 0:
                page_size = first_page_count
                self.page_size = page_size
                self.logger.debug(f"DOM page_size: {page_size} (첫 페이지 상품 수)")
        except Exception as e:
            self.logger.debug(f"DOM 전체건수 추출 실패: {e}")

        # 2) DOM에서 못 읽은 경우 __PRELOADED_STATE__ 폴백
        if total_count == 0 or page_size == 0:
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
                                if total_count == 0:
                                    total_count = sub_data.get('totalCount', 0)
                                if page_size == 0:
                                    page_size = sub_data.get('pageSize', self.naver_config.ITEMS_PER_PAGE)
                                    self.page_size = page_size
                                break
            except Exception as e:
                self.logger.debug(f"__PRELOADED_STATE__ 폴백 실패: {e}")

        # 최종 폴백
        if page_size == 0:
            page_size = self.naver_config.ITEMS_PER_PAGE
            self.page_size = page_size

        # 3) __PRELOADED_STATE__에서 카테고리명, channel_id 추출 (별도)
        try:
            html = await self.page.content()
            match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});?\s*</script>', html, re.DOTALL)
            if match:
                state_data = json.loads(match.group(1))

                # 스토어 카테고리 이름 추출
                category_names = state_data.get('categoryNames', {})
                if category_names:
                    a_data = category_names.get('A', {})
                    if a_data and url_info.get('category_id'):
                        cat_id = url_info['category_id']
                        if cat_id in a_data:
                            self.current_store_category = a_data[cat_id]
                            self.logger.debug(f"스토어 카테고리: {self.current_store_category}")
                        else:
                            store_cat = state_data.get('storeCategory', {})
                            a_store = store_cat.get('A', {})
                            first_cats = a_store.get('firstCategories', [])
                            for cat in first_cats:
                                if cat.get('id') == cat_id or cat.get('categoryId') == cat_id:
                                    self.current_store_category = cat.get('name', '')
                                    self.logger.debug(f"스토어 카테고리 (firstCategories): {self.current_store_category}")
                                    break

                # channel_id 추출
                if not self.channel_id:
                    channel_info = state_data.get('channel', {})
                    if isinstance(channel_info, dict):
                        cid = channel_info.get('channelNo') or channel_info.get('id')
                        if not cid:
                            for v in channel_info.values():
                                if isinstance(v, dict):
                                    cid = v.get('channelNo') or v.get('id')
                                    if cid:
                                        break
                        if cid:
                            self.channel_id = str(cid)
                            self.logger.debug(f"channel_id (PRELOADED_STATE): {self.channel_id}")
                    if not self.channel_id:
                        for key, val in state_data.items():
                            if isinstance(val, dict):
                                cid = val.get('channelNo') or val.get('channelId')
                                if cid:
                                    self.channel_id = str(cid)
                                    self.logger.debug(f"channel_id (nested): {self.channel_id}")
                                    break
        except Exception as e:
            self.logger.debug(f"카테고리/channel_id 추출 실패: {e}")

        if self.channel_id:
            self.log(f"  channel_id: {self.channel_id}")

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
                    if not page_products:
                        # PRELOADED_STATE에 상품이 없으면 DOM 폴백 (all 카테고리 등)
                        self.logger.debug("PRELOADED_STATE 비어있음 → DOM 추출 폴백")
                        page_products = await self._extract_from_dom()
                else:
                    # 페이지 2+: DOM에서 상품 추출
                    page_products = await self._extract_from_dom()

                if not page_products:
                    self.log(f"  ⚠️ 페이지 {current_page}: 상품 없음")
                    break

                # 중복 제거: 이미 수집된 product_id는 스킵
                new_products = []
                for p in page_products:
                    if p.product_id not in seen_ids:
                        seen_ids.add(p.product_id)
                        new_products.append(p)

                if not new_products and page_products:
                    # 모든 상품이 중복이면 페이지 전환이 안 된 것 → 중단
                    self.log(f"  ⚠️ 페이지 {current_page}: 모든 상품이 중복 (페이지 전환 실패) → 수집 중단")
                    break

                self.log(f"  ✓ 페이지 {current_page}: {len(new_products)}개 상품 (중복 제외)")
                products.extend(new_products)

                # totalCount가 0이었지만 DOM에서 상품을 찾은 경우, total_pages 재계산
                if total_count == 0 and len(new_products) >= page_size:
                    # DOM에서 페이지 수 추출 시도 (숫자 링크 그룹 탐색)
                    dom_total_pages = await self.page.evaluate("""
                        () => {
                            const allEls = document.querySelectorAll('a, button');
                            const numberEls = [];
                            for (const el of allEls) {
                                const text = el.textContent.trim();
                                if (/^\\d+$/.test(text) && parseInt(text) <= 100 && el.offsetParent !== null) {
                                    numberEls.push({ num: parseInt(text), className: el.className });
                                }
                            }
                            // 같은 클래스 그룹 중 가장 큰 그룹에서 최대 페이지 번호 추출
                            const classGroups = {};
                            for (const el of numberEls) {
                                if (!classGroups[el.className]) classGroups[el.className] = [];
                                classGroups[el.className].push(el.num);
                            }
                            let maxPage = 1;
                            let maxGroupSize = 0;
                            for (const [cls, nums] of Object.entries(classGroups)) {
                                if (nums.length > maxGroupSize) {
                                    maxGroupSize = nums.length;
                                    maxPage = Math.max(...nums);
                                }
                            }
                            return maxPage;
                        }
                    """)
                    if dom_total_pages > total_pages:
                        total_pages = dom_total_pages
                        self.state.total_pages = total_pages
                        self.log(f"  페이지 수 업데이트: {total_pages}페이지")

                # 페이지네이션 확인
                if end_page and current_page >= end_page:
                    has_next = False
                elif current_page >= total_pages:
                    has_next = False
                else:
                    # 다음 페이지로 이동 (하단 버튼 클릭)
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

                # 가격 정렬: 높은 가격을 price에, 낮은 가격을 sale_price에
                if sale_price > original_price and original_price > 0:
                    original_price, sale_price = sale_price, original_price

                brand_info = item.get('naverShoppingSearchInfo', {})
                brand = brand_info.get('brandName', '')

                product_id = str(item.get('id', ''))
                if self.store_type == "brand":
                    product_url = f"https://brand.naver.com/{self.store_name}/products/{product_id}"
                else:
                    product_url = f"https://smartstore.naver.com/{self.store_name}/products/{product_id}"

                # 카테고리 정보: categoryNavigations에서 추출 (상품별 스토어 카테고리)
                cat_nav = item.get('categoryNavigations', [])
                if cat_nav:
                    # categoryNavigations에서 카테고리 이름들을 > 로 연결
                    category_name = '>'.join([c.get('categoryName', '') for c in cat_nav if c.get('categoryName')])
                else:
                    # 폴백1: 카테고리 목록 페이지의 스토어 카테고리
                    category_name = self.current_store_category
                    if not category_name:
                        # 폴백2: 네이버 쇼핑 카테고리
                        item_category = item.get('category', {})
                        if item_category:
                            category_name = item_category.get('wholeCategoryName', '')

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
                        'category': category_name,  # 카테고리 추가
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

                # 가격 정렬: 높은 가격을 price에, 낮은 가격을 sale_price에
                price = item.get('price', 0)
                sale_price = item.get('salePrice', 0)
                if sale_price > price and price > 0:
                    price, sale_price = sale_price, price

                product = ProductInfo(
                    product_id=product_id,
                    product_name=item.get('name', ''),
                    brand=self.store_name,
                    price=price,
                    sale_price=sale_price,
                    image_url=item.get('imgUrl', ''),
                    url=product_url,
                    extra_info={
                        'option_usable': False,  # collect_product_detail에서 API 응답으로 갱신됨
                        'category': self.current_store_category,  # 스토어 카테고리
                    }
                )
                products.append(product)

            return products
        except Exception as e:
            self.logger.error(f"DOM 추출 실패: {e}")
            return []

    async def _navigate_to_page(self, target_page: int) -> bool:
        """페이지 번호 버튼을 클릭하여 특정 페이지로 이동"""
        try:
            # 페이지 번호 버튼 클릭: 숫자만 있는 a/button 태그 중 동일 클래스가 여러 개인 그룹 찾기
            result = await self.page.evaluate("""
                (targetPage) => {
                    // 숫자만 포함된 a/button 태그를 모두 수집
                    const allLinks = document.querySelectorAll('a, button');
                    const numberLinks = [];
                    for (const el of allLinks) {
                        const text = el.textContent.trim();
                        if (/^\d+$/.test(text) && parseInt(text) <= 100 && el.offsetParent !== null) {
                            numberLinks.push({ el, num: parseInt(text), className: el.className });
                        }
                    }

                    // 같은 클래스를 공유하는 숫자 링크 그룹 찾기 (페이지네이션 패턴)
                    const classGroups = {};
                    for (const link of numberLinks) {
                        const cls = link.className;
                        if (!classGroups[cls]) classGroups[cls] = [];
                        classGroups[cls].push(link);
                    }

                    // 가장 큰 그룹이 페이지네이션 (2개 이상 연속 숫자)
                    let paginationGroup = null;
                    let maxSize = 0;
                    for (const [cls, links] of Object.entries(classGroups)) {
                        if (links.length > maxSize) {
                            maxSize = links.length;
                            paginationGroup = links;
                        }
                    }

                    if (paginationGroup) {
                        // 현재 보이는 페이지 번호 범위 확인
                        const visiblePages = paginationGroup.map(l => l.num).sort((a, b) => a - b);
                        const minVisible = visiblePages[0];
                        const maxVisible = visiblePages[visiblePages.length - 1];

                        // 타겟 페이지가 현재 보이는 범위에 있으면 직접 클릭
                        for (const link of paginationGroup) {
                            if (link.num === targetPage) {
                                link.el.click();
                                return { clicked: true, action: 'direct' };
                            }
                        }

                        // 타겟 페이지가 현재 범위보다 크면 "다음" 버튼 찾기
                        if (targetPage > maxVisible) {
                            // 페이지네이션 컨테이너 찾기 (페이지 번호 버튼의 부모)
                            const firstPageBtn = paginationGroup[0].el;
                            const container = firstPageBtn.closest('nav') || firstPageBtn.parentElement?.parentElement;

                            if (container) {
                                // "다음" 버튼 찾기 (>, 다음, next 등)
                                const nextBtns = container.querySelectorAll('a, button');
                                for (const btn of nextBtns) {
                                    const text = btn.textContent.trim();
                                    const ariaLabel = btn.getAttribute('aria-label') || '';
                                    const title = btn.getAttribute('title') || '';

                                    // ">" 또는 "다음" 또는 화살표 아이콘 버튼
                                    if (text === '>' || text === '다음' || text === 'next' ||
                                        text.includes('다음') || ariaLabel.includes('다음') ||
                                        ariaLabel.includes('next') || title.includes('다음') ||
                                        btn.querySelector('svg[class*="right"]') ||
                                        btn.querySelector('[class*="next"]') ||
                                        btn.querySelector('[class*="arrow"]')) {

                                        // 숫자 버튼이 아닌 경우만 클릭
                                        if (!/^\d+$/.test(text)) {
                                            btn.click();
                                            return { clicked: true, action: 'next_group' };
                                        }
                                    }
                                }
                            }
                        }
                    }

                    return { clicked: false, action: null };
                }
            """, target_page)

            if result.get('clicked'):
                action = result.get('action')
                # 페이지 전환 대기
                await asyncio.sleep(2)
                await self.page.evaluate('window.scrollTo(0, 0)')
                await asyncio.sleep(0.5)

                # "다음 그룹" 버튼을 클릭한 경우, 타겟 페이지 버튼을 다시 클릭
                if action == 'next_group':
                    self.log(f"    → 다음 페이지 그룹으로 이동")
                    await asyncio.sleep(1)
                    # 재귀적으로 다시 시도 (새 페이지 그룹에서 타겟 페이지 클릭)
                    return await self._navigate_to_page(target_page)

                return True

            # 버튼 클릭 실패 → URL 기반 네비게이션 폴백
            self.log(f"    ⚠️ 페이지 {target_page} 버튼을 찾지 못함 → URL 이동 시도")
            return await self._navigate_to_page_by_url(target_page)

        except Exception as e:
            self.logger.error(f"페이지 {target_page} 이동 실패: {e}")
            # 예외 시에도 URL 폴백 시도
            try:
                return await self._navigate_to_page_by_url(target_page)
            except Exception:
                return False

    async def _navigate_to_page_by_url(self, target_page: int) -> bool:
        """URL 직접 변경으로 페이지 이동 (버튼 클릭 실패 시 폴백)"""
        try:
            page_url = self._build_page_url(self.state.url, target_page)
            self.log(f"    → URL 이동: page={target_page}")
            await self.page.goto(page_url, wait_until="networkidle", timeout=30000)
            await asyncio.sleep(2)
            return True
        except Exception as e:
            self.logger.error(f"URL 기반 페이지 이동 실패: {e}")
            return False

    def _build_page_url(self, base_url: str, page: int) -> str:
        """페이지 URL 생성"""
        parsed = urlparse(base_url)
        query = parse_qs(parsed.query)

        # 페이지 파라미터 설정 (page와 cp 모두 업데이트)
        query['page'] = [str(page)]
        query['cp'] = [str(page)]
        if 'st' not in query:
            query['st'] = ['POPULAR']
        if 'dt' not in query:
            query['dt'] = ['BIG_IMAGE']
        effective_size = self.page_size or self.naver_config.ITEMS_PER_PAGE
        query['size'] = [str(effective_size)]

        query_str = '&'.join(f"{k}={v[0]}" for k, v in query.items())
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query_str}"

    async def _fetch_product_api(self, product_id: str) -> Optional[Dict]:
        """channel_id를 이용해 page.evaluate(fetch)로 상품 API 직접 호출 (페이지 네비게이션 불필요)"""
        if not self.channel_id:
            return None

        base_domain = "brand.naver.com" if self.store_type == "brand" else "smartstore.naver.com"
        api_url = f"https://{base_domain}/n/v2/channels/{self.channel_id}/products/{product_id}?withWindow=false"

        try:
            data = await self.page.evaluate("""
                async (url) => {
                    try {
                        const resp = await fetch(url, { credentials: 'include' });
                        if (!resp.ok) return { __error: resp.status };
                        return await resp.json();
                    } catch (e) {
                        return { __error: e.message };
                    }
                }
            """, api_url)

            if data and '__error' not in data:
                return data
            else:
                err = data.get('__error', 'unknown') if data else 'null'
                self.logger.debug(f"fetch API 실패 [{product_id}]: {err}")
                return None
        except Exception as e:
            self.logger.debug(f"page.evaluate fetch 실패 [{product_id}]: {e}")
            return None

    async def _fetch_content_api(self, product_id: str, product_no: str = None) -> Optional[Dict]:
        """channel_id를 이용해 상품 상세설명(renderContent) API 호출"""
        if not self.channel_id or not product_no:
            return None

        base_domain = "brand.naver.com" if self.store_type == "brand" else "smartstore.naver.com"
        content_url = f"https://{base_domain}/n/v2/channels/{self.channel_id}/products/{product_id}/contents/{product_no}/PC"

        try:
            data = await self.page.evaluate("""
                async (url) => {
                    try {
                        const resp = await fetch(url, { credentials: 'include' });
                        if (!resp.ok) return { __error: resp.status };
                        return await resp.json();
                    } catch (e) {
                        return { __error: e.message };
                    }
                }
            """, content_url)

            if data and '__error' not in data and 'renderContent' in data:
                return data
            else:
                self.logger.debug(f"content API 응답 없음 [{product_id}]")
                return None
        except Exception as e:
            self.logger.debug(f"content API fetch 실패 [{product_id}]: {e}")
            return None

    async def _fetch_products_batch(self, product_ids: List[str]) -> Dict[str, Optional[Dict]]:
        """여러 상품을 배치로 fetch (Promise.all)"""
        if not self.channel_id or not product_ids:
            return {}

        base_domain = "brand.naver.com" if self.store_type == "brand" else "smartstore.naver.com"
        urls = {
            pid: f"https://{base_domain}/n/v2/channels/{self.channel_id}/products/{pid}?withWindow=false"
            for pid in product_ids
        }

        try:
            results = await self.page.evaluate("""
                async (urlMap) => {
                    const entries = Object.entries(urlMap);
                    const results = {};
                    const batchSize = 5;
                    for (let i = 0; i < entries.length; i += batchSize) {
                        const batch = entries.slice(i, i + batchSize);
                        const promises = batch.map(async ([pid, url]) => {
                            try {
                                const resp = await fetch(url, { credentials: 'include' });
                                if (!resp.ok) return [pid, null];
                                const data = await resp.json();
                                return [pid, data];
                            } catch (e) {
                                return [pid, null];
                            }
                        });
                        const batchResults = await Promise.all(promises);
                        for (const [pid, data] of batchResults) {
                            results[pid] = data;
                        }
                        // 배치 간 짧은 딜레이
                        if (i + batchSize < entries.length) {
                            await new Promise(r => setTimeout(r, 200));
                        }
                    }
                    return results;
                }
            """, urls)
            return results or {}
        except Exception as e:
            self.logger.debug(f"배치 fetch 실패: {e}")
            return {}

    async def collect_product_detail(self, product: ProductInfo) -> ProductInfo:
        """상품 상세 정보 수집 (channel_id가 있으면 fetch API, 없으면 page.goto 폴백)"""
        product_id = product.product_id
        detail_url = product.url

        product_data = None
        content_data = None

        # 방법 1: channel_id가 있으면 page.evaluate(fetch)로 직접 API 호출
        if self.channel_id:
            product_data = await self._fetch_product_api(product_id)
            if product_data:
                self.logger.debug(f"fetch API 성공 [{product_id}]")
                # 상세설명(renderContent)도 fetch (productNo 필요)
                product_no = product_data.get('productNo', '')
                if product_no:
                    content_data = await self._fetch_content_api(product_id, str(product_no))

        # 방법 2: 폴백 - 기존 page.goto 방식
        if not product_data:
            self.logger.debug(f"page.goto 폴백 [{product_id}]")

            async def capture_product_response(response):
                nonlocal product_data, content_data
                try:
                    url = response.url
                    if f'/products/{product_id}' in url and ('withWindow' in url or url.endswith(f'/products/{product_id}')):
                        if response.status == 200:
                            try:
                                data = await response.json()
                                if 'optionCombinations' in data or 'name' in data:
                                    product_data = data
                                    self.logger.debug(f"API 응답 캡처: {url[:80]}...")
                            except:
                                pass
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
                await self.page.goto(detail_url, wait_until="domcontentloaded", timeout=60000)
                for _ in range(20):
                    if product_data:
                        break
                    await asyncio.sleep(0.5)
            except Exception as e:
                self.logger.warning(f"페이지 로딩 중 오류: {e}")
                await asyncio.sleep(2)
            finally:
                self.page.remove_listener('response', capture_product_response)

        # 카테고리 정보 수집 - 페이지 방문 후 __PRELOADED_STATE__에서 추출
        if self.page and not product.extra_info.get('category'):
            try:
                # __PRELOADED_STATE__에서 categoryNavigations 추출
                html = await self.page.content()
                preload_match = re.search(r'window\.__PRELOADED_STATE__\s*=\s*({.+?});?\s*</script>', html, re.DOTALL)
                if preload_match:
                    state_data = json.loads(preload_match.group(1))

                    # simpleProductForDetailPage에서 categoryNavigations 찾기
                    simple_prod = state_data.get('simpleProductForDetailPage', {})
                    a_data = simple_prod.get('A', {})
                    cat_nav = a_data.get('categoryNavigations', [])

                    if cat_nav:
                        category = '>'.join([c.get('categoryName', '') for c in cat_nav if c.get('categoryName')])
                        if category:
                            product.extra_info['category'] = category
                            self.logger.debug(f"카테고리 수집 (PRELOADED_STATE): {category}")
            except Exception as e:
                self.logger.debug(f"PRELOADED_STATE 카테고리 추출 실패: {e}")

        if product_data:
            # 가격 정보 수정: 배송비와 판매가 분리
            # - Price (정가) 란에 → 배송비 (화면에 표시된 값 기준)
            # - Sale_Price (판매가) → 실제 판매가
            # - Total_Price → 배송비 + 판매가
            delivery_info = product_data.get('productDeliveryInfo', {})
            delivery_fee_type = delivery_info.get('deliveryFeeType', '')
            base_fee = delivery_info.get('baseFee', 0) or 0

            # 실제 판매가 (benefitsView.discountedSalePrice 우선, 없으면 salePrice)
            benefits = product_data.get('benefitsView', {})
            actual_sale_price = benefits.get('discountedSalePrice', 0) or product_data.get('salePrice', 0)

            # 배송비 계산: DOM에서 실제 표시되는 값을 먼저 확인
            # (판매자가 "무료배송" 설정 시 API와 다를 수 있음)
            delivery_fee = None
            dom_delivery_source = None

            if self.page:
                try:
                    # 페이지 렌더링 대기
                    await asyncio.sleep(1)

                    dom_delivery = await self.page.evaluate('''() => {
                        const result = { found: false, isFree: false, fee: 0, debug: '' };
                        const allText = document.body.innerText;
                        const lines = allText.split('\\n');

                        for (let i = 0; i < lines.length; i++) {
                            const line = lines[i].trim();
                            // "배송비" 키워드가 있는 라인 찾기 (정확히 "배송비"만 있는 라인)
                            if (line === '배송비') {
                                // 다음 라인에서 배송비 정보 확인
                                if (i + 1 < lines.length) {
                                    const nextLine = lines[i + 1].trim();
                                    result.debug = nextLine;

                                    // 무료배송 체크
                                    if (nextLine === '무료배송' || nextLine.startsWith('무료배송')) {
                                        result.isFree = true;
                                        result.fee = 0;
                                        result.found = true;
                                        break;
                                    }
                                    // 금액 패턴 확인 (예: "3,000원", "무료")
                                    if (nextLine === '무료' || nextLine.startsWith('무료')) {
                                        result.isFree = true;
                                        result.fee = 0;
                                        result.found = true;
                                        break;
                                    }
                                    const feeMatch = nextLine.match(/^([0-9,]+)원/);
                                    if (feeMatch) {
                                        result.fee = parseInt(feeMatch[1].replace(/,/g, ''));
                                        result.found = true;
                                        break;
                                    }
                                }
                            }
                        }
                        return result;
                    }''')

                    if dom_delivery.get('found'):
                        delivery_fee = dom_delivery.get('fee', 0)
                        dom_delivery_source = 'DOM'
                        self.logger.debug(f"DOM 배송비: {delivery_fee}원 (무료: {dom_delivery.get('isFree')}, debug: {dom_delivery.get('debug')})")
                    else:
                        self.logger.debug(f"DOM 배송비 미발견 (debug: {dom_delivery.get('debug')})")
                except Exception as e:
                    self.logger.debug(f"DOM 배송비 추출 실패: {e}")

            # DOM에서 못 찾으면 API 데이터 기반으로 계산 (폴백)
            if delivery_fee is None:
                free_condition = delivery_info.get('freeConditionalAmount', 0) or 0
                if delivery_fee_type == 'FREE':
                    delivery_fee = 0
                elif delivery_fee_type == 'CONDITIONAL_FREE' and actual_sale_price >= free_condition:
                    delivery_fee = 0
                else:
                    delivery_fee = base_fee
                dom_delivery_source = 'API'
                self.logger.debug(f"API 배송비: {delivery_fee}원 (type: {delivery_fee_type})")

            # 가격 필드 업데이트
            product.price = delivery_fee  # Price 란에 배송비
            product.sale_price = actual_sale_price  # Sale_Price에 판매가
            product.extra_info['delivery_fee'] = delivery_fee  # 참고용
            product.extra_info['delivery_fee_type'] = delivery_fee_type  # 참고용
            product.extra_info['delivery_source'] = dom_delivery_source  # 배송비 출처

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

                # KC 인증정보 (상품정보제공고시 내)
                kc_info = basic.get('KC 인증정보', '')
                if kc_info:
                    product.extra_info['kc_certification'] = kc_info

            # productCertificationInfos (인증 정보 상세)
            cert_infos = product_data.get('productCertificationInfos', [])
            if cert_infos:
                cert_list = []
                for cert in cert_infos:
                    cert_entry = {
                        'type': cert.get('certificationTypeName', ''),
                        'agency': cert.get('name', ''),
                        'number': cert.get('certificationNumber', ''),
                        'company': cert.get('companyName', ''),
                    }
                    cert_list.append(cert_entry)

                product.extra_info['certification_infos'] = cert_list

                # description에 인증 정보 추가 (기존 description에 병합)
                cert_texts = []
                for cert in cert_list:
                    parts = [cert['type']]
                    if cert['agency']:
                        parts.append(f"인증기관: {cert['agency']}")
                    if cert['number']:
                        parts.append(f"인증번호: {cert['number']}")
                    if cert['company']:
                        parts.append(f"제조사: {cert['company']}")
                    cert_texts.append(' / '.join(parts))

                cert_text = '[인증정보]\n' + '\n'.join(cert_texts)
                existing_desc = product.extra_info.get('description', '')
                if existing_desc:
                    product.extra_info['description'] = existing_desc + '\n\n' + cert_text
                else:
                    product.extra_info['description'] = cert_text

                self.logger.debug(f"인증 정보 {len(cert_list)}건 수집")

            # detailAttributes (상세속성) - 카테고리별로 다름
            detail_attrs = product_data.get('detailAttributes', {})
            if detail_attrs:
                # 일반 속성
                for key, value in detail_attrs.items():
                    # 키를 영문으로 변환
                    eng_key = self._korean_key_to_english(key)
                    product.extra_info[eng_key] = value

                # description에 상세속성 추가
                attr_lines = [f"{key}: {value}" for key, value in detail_attrs.items() if value]
                if attr_lines:
                    attr_text = '[상품속성]\n' + '\n'.join(attr_lines)
                    existing_desc = product.extra_info.get('description', '')
                    if existing_desc:
                        product.extra_info['description'] = attr_text + '\n\n' + existing_desc
                    else:
                        product.extra_info['description'] = attr_text

            # productAttributes (상품 속성 - 구조화된 형태)
            prod_attrs = product_data.get('productAttributes', [])
            if prod_attrs:
                # 같은 attributeName을 가진 항목 그룹핑 (예: 장르가 여러 개)
                attr_map = {}
                for attr in prod_attrs:
                    name = attr.get('attributeName', '')
                    val = attr.get('minAttributeValue', '')
                    unit = attr.get('minAttributeValueUnitText', '')
                    if name and val:
                        full_val = f"{val}{unit}" if unit else val
                        if name in attr_map:
                            attr_map[name] += f", {full_val}"
                        else:
                            attr_map[name] = full_val

                if attr_map:
                    pa_lines = [f"{k}: {v}" for k, v in attr_map.items()]
                    pa_text = '[상품속성]\n' + '\n'.join(pa_lines)

                    existing_desc = product.extra_info.get('description', '')
                    # 이미 detailAttributes로 [상품속성]이 있으면 중복 방지
                    if '[상품속성]' not in existing_desc:
                        if existing_desc:
                            product.extra_info['description'] = pa_text + '\n\n' + existing_desc
                        else:
                            product.extra_info['description'] = pa_text

            # 추가 이미지 수집 (갤러리 이미지) - API productImages 사용
            product_images = product_data.get('productImages', []) or product_data.get('galleryImages', [])
            if product_images:
                extra_images = [img.get('url', '') for img in product_images if img.get('url')]
                if extra_images:
                    # 첫 번째 이미지를 대표 이미지로 설정
                    product.image_url = extra_images[0]
                    product.extra_info['extra_images'] = extra_images

        # 상세 설명 수집 (renderContent에서 이미지 + 텍스트 추출)
        if content_data:
            render_content = content_data.get('renderContent', '')
            if render_content:
                # 우선순위 1: se-image-resource 클래스 이미지 (네이버 스마트 에디터)
                se_images = re.findall(
                    r'<img[^>]*class="[^"]*se-image-resource[^"]*"[^>]*src="([^"]+)"',
                    render_content
                )
                # src/class 순서 반대인 경우도 처리
                se_images += re.findall(
                    r'<img[^>]*src="([^"]+)"[^>]*class="[^"]*se-image-resource[^"]*"',
                    render_content
                )
                se_images = list(dict.fromkeys(u for u in se_images if u.startswith('http')))

                # 우선순위 2: 외부 CDN 이미지 (Naver CDN 제외)
                # phinf.pstatic.net (checkout.phinf 포함), shop-phinf.pstatic.net 제외
                naver_cdn_patterns = ['phinf.pstatic.net', 'ssl.pstatic.net', 'storep-phinf.pstatic.net']
                all_imgs = re.findall(r'<img[^>]+src="([^"]+)"', render_content)
                external_imgs = [
                    url for url in all_imgs
                    if url.startswith('http') and not any(cdn in url for cdn in naver_cdn_patterns)
                ]
                external_imgs = list(dict.fromkeys(external_imgs))

                # 배너 패턴 필터링
                banner_patterns = [
                    'officialsite', 'top_renewal', 'flavor%20of%20the%20month',
                    'flavor of the month', '/banner/', '/promotion/', '/event/', '/common/'
                ]
                def is_not_banner(url):
                    lower_url = url.lower()
                    return not any(p in lower_url for p in banner_patterns)

                # 최종 상세 이미지: se-image-resource + 외부 CDN
                detail_images = [u for u in (se_images + external_imgs) if is_not_banner(u)]
                detail_images = list(dict.fromkeys(detail_images))

                # 폴백: se/외부 이미지가 없으면 shop-phinf 이미지 사용 (단 checkout.phinf 제외)
                if not detail_images:
                    all_http = [u for u in all_imgs if u.startswith('http')]
                    detail_images = [
                        u for u in all_http
                        if is_not_banner(u) and 'checkout.phinf' not in u
                    ]
                    detail_images = list(dict.fromkeys(detail_images))

                if detail_images:
                    product.extra_info['detail_images'] = detail_images
                    self.logger.debug(f"상세 이미지 {len(detail_images)}개 수집")

                # HTML에서 텍스트 추출 (태그 제거)
                desc_text = re.sub(r'<style[^>]*>.*?</style>', '', render_content, flags=re.DOTALL)
                desc_text = re.sub(r'<script[^>]*>.*?</script>', '', desc_text, flags=re.DOTALL)
                desc_text = re.sub(r'<br\s*/?>', '\n', desc_text)
                desc_text = re.sub(r'</p>', '\n', desc_text)
                desc_text = re.sub(r'</div>', '\n', desc_text)
                desc_text = re.sub(r'<[^>]+>', '', desc_text)
                desc_text = re.sub(r'&nbsp;', ' ', desc_text)
                desc_text = re.sub(r'&amp;', '&', desc_text)
                desc_text = re.sub(r'&lt;', '<', desc_text)
                desc_text = re.sub(r'&gt;', '>', desc_text)
                desc_text = re.sub(r'\n{3,}', '\n\n', desc_text)
                desc_text = desc_text.strip()
                if desc_text:
                    product.extra_info['description'] = desc_text
                    self.logger.debug(f"상세설명 텍스트 {len(desc_text)}자 수집")

        # 상품 상세 페이지에 있을 때 DOM 직접 수집 (renderContent보다 우선)
        # page.goto로 상품 페이지 방문 시 실행 (API 전용 수집 시에는 카테고리 페이지이므로 스킵)
        if self.page and product_id in self.page.url:
            try:
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

                dom_product_images = await self.page.evaluate("""
                    () => {
                        const images = [];
                        const seen = new Set();

                        const bannerPatterns = [
                            'officialsite', 'top_renewal', '/banner/', '/promotion/', '/event/', '/common/'
                        ];
                        const isBanner = (src) => bannerPatterns.some(p => src.toLowerCase().includes(p));

                        // 1순위: se-image-resource (네이버 스마트 에디터)
                        document.querySelectorAll('img.se-image-resource').forEach(img => {
                            const src = img.dataset.src || img.dataset.lazySrc || img.src || '';
                            if (src && src.startsWith('http') && !seen.has(src) && !isBanner(src)) {
                                seen.add(src);
                                images.push(src);
                            }
                        });
                        if (images.length > 0) return images.slice(0, 50);

                        // 2순위: "상세정보 펼쳐보기" 버튼 이전 div (collapsible 섹션)
                        const expandBtn = [...document.querySelectorAll('button')].find(
                            b => b.textContent.trim().includes('상세정보 펼쳐보기')
                        );
                        if (expandBtn) {
                            const prevDiv = expandBtn.previousElementSibling;
                            if (prevDiv) {
                                prevDiv.querySelectorAll('img').forEach(img => {
                                    const src = img.dataset.src || img.src || '';
                                    if (src && src.startsWith('http') && !src.startsWith('data:') &&
                                        !seen.has(src) && !isBanner(src)) {
                                        seen.add(src);
                                        images.push(src);
                                    }
                                });
                            }
                        }
                        return images.slice(0, 50);
                    }
                """)

                if dom_product_images:
                    product.extra_info['detail_images'] = dom_product_images
                    self.logger.debug(f"상세 이미지 (상품페이지 DOM) {len(dom_product_images)}개 수집")
            except Exception as e:
                self.logger.debug(f"상품페이지 DOM 이미지 추출 실패: {e}")

        # 상세 이미지 폴백: renderContent에서 수집 못한 경우 DOM에서 추출
        if not product.extra_info.get('detail_images') and self.page:
            try:
                # 스크롤하여 lazy-load 트리거
                await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await asyncio.sleep(1)

                # DOM에서 상세 이미지 추출
                dom_detail_images = await self.page.evaluate("""
                    () => {
                        const images = [];
                        const seen = new Set();
                        const repSrc = (document.querySelector("img[alt='대표이미지']") || {}).src || '';

                        // 배너/UI 이미지 제외 패턴
                        const bannerPatterns = [
                            'officialsite', 'top_renewal', '/banner/', '/promotion/', '/event/', '/common/'
                        ];
                        const isBanner = (src) => bannerPatterns.some(p => src.toLowerCase().includes(p));

                        // 1순위: se-image-resource (네이버 스마트 에디터)
                        // data-src 우선 (lazy-load 실제 URL)
                        document.querySelectorAll('img.se-image-resource').forEach(img => {
                            const src = img.dataset.src || img.dataset.lazySrc || img.src || '';
                            if (src && src.startsWith('http') && !seen.has(src) && !isBanner(src)) {
                                seen.add(src);
                                images.push(src);
                            }
                        });

                        if (images.length > 0) return images.slice(0, 50);

                        // 2순위: se-module-image-link의 data-linkdata
                        document.querySelectorAll('a.se-module-image-link[data-linkdata]').forEach(link => {
                            try {
                                const src = JSON.parse(link.getAttribute('data-linkdata')).src || '';
                                if (src && src.startsWith('http') && !seen.has(src)) {
                                    seen.add(src); images.push(src);
                                }
                            } catch (e) {}
                        });

                        if (images.length > 0) return images.slice(0, 50);

                        // 3순위: data-src가 http로 시작하는 외부 CDN img 태그
                        // 대표이미지 제외, 배너 제외, Naver CDN(phinf.pstatic.net) 제외
                        const naverCdns = ['phinf.pstatic.net', 'ssl.pstatic.net'];
                        document.querySelectorAll('img[data-src]').forEach(img => {
                            const src = img.dataset.src || '';
                            if (src && src.startsWith('http') &&
                                src !== repSrc &&
                                !seen.has(src) &&
                                !isBanner(src) &&
                                !naverCdns.some(cdn => src.includes(cdn))) {
                                seen.add(src);
                                images.push(src);
                            }
                        });

                        return images.slice(0, 50);
                    }
                """)

                if dom_detail_images:
                    product.extra_info['detail_images'] = dom_detail_images
                    self.logger.debug(f"상세 이미지 (DOM 폴백) {len(dom_detail_images)}개 수집")
            except Exception as e:
                self.logger.debug(f"DOM 상세 이미지 추출 실패: {e}")

        # 옵션 수집 - optionCombinations에서 추출 (API 기반)
        # API 응답의 optionUsable 사용 (page 2+ 상품도 옵션 수집 가능)
        option_usable = product_data.get('optionUsable', False) if product_data else product.extra_info.get('option_usable', False)
        product.extra_info['option_usable'] = option_usable
        if product_data and option_usable:
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
                self.logger.debug(f"옵션 수집 (API optionCombinations): {len(options)}개")

            # simpleOptions 지원 (optionCombinations가 없는 경우)
            elif not option_combinations:
                simple_options = product_data.get('simpleOptions', [])
                if simple_options:
                    options = []
                    for group in simple_options:
                        group_name = group.get('groupName', '선택')
                        opts = group.get('options', [])
                        for opt in opts:
                            opt_name = opt.get('name', '')
                            opt_id = opt.get('id', '')
                            # simpleOptions는 추가금액/재고 정보가 없는 경우가 많음
                            # 기본값 사용
                            options.append(ProductOption(
                                color='',
                                size=opt_name,
                                additional_price=0,
                                stock=100,  # 기본값
                                sold_out=False,
                                option_data={group_name: opt_name, 'option_id': opt_id},
                            ))
                    if options:
                        product.options = options
                        self.logger.debug(f"옵션 수집 (API simpleOptions): {len(options)}개")

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
