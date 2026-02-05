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

                # 스토어 카테고리 이름 추출 (categoryNames에서)
                category_names = state_data.get('categoryNames', {})
                if category_names:
                    a_data = category_names.get('A', {})
                    if a_data and url_info.get('category_id'):
                        cat_id = url_info['category_id']
                        # categoryNames에서 해당 카테고리 ID의 이름 찾기
                        if cat_id in a_data:
                            self.current_store_category = a_data[cat_id]
                            self.logger.debug(f"스토어 카테고리: {self.current_store_category}")
                        else:
                            # storeCategory.firstCategories에서 찾기
                            store_cat = state_data.get('storeCategory', {})
                            a_store = store_cat.get('A', {})
                            first_cats = a_store.get('firstCategories', [])
                            for cat in first_cats:
                                if cat.get('id') == cat_id or cat.get('categoryId') == cat_id:
                                    self.current_store_category = cat.get('name', '')
                                    self.logger.debug(f"스토어 카테고리 (firstCategories): {self.current_store_category}")
                                    break

                # __PRELOADED_STATE__에서 channel_id 폴백 추출
                if not self.channel_id:
                    # 방법1: channel 키 직접 탐색
                    channel_info = state_data.get('channel', {})
                    if isinstance(channel_info, dict):
                        cid = channel_info.get('channelNo') or channel_info.get('id')
                        if not cid:
                            # {'A': {channelNo: ...}} 형태 대응
                            for v in channel_info.values():
                                if isinstance(v, dict):
                                    cid = v.get('channelNo') or v.get('id')
                                    if cid:
                                        break
                        if cid:
                            self.channel_id = str(cid)
                            self.logger.debug(f"channel_id (PRELOADED_STATE): {self.channel_id}")
                    # 방법2: 중첩 탐색
                    if not self.channel_id:
                        for key, val in state_data.items():
                            if isinstance(val, dict):
                                cid = val.get('channelNo') or val.get('channelId')
                                if cid:
                                    self.channel_id = str(cid)
                                    self.logger.debug(f"channel_id (nested): {self.channel_id}")
                                    break
        except Exception as e:
            self.logger.debug(f"__PRELOADED_STATE__ 파싱 실패: {e}")

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
                    # DOM에서 페이지 수 추출 시도
                    dom_total_pages = await self.page.evaluate("""
                        () => {
                            const btns = document.querySelectorAll('a[class*="pagination"], button[class*="pagination"]');
                            let maxPage = 1;
                            for (const btn of btns) {
                                const num = parseInt(btn.textContent.trim());
                                if (!isNaN(num) && num > maxPage) maxPage = num;
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

                brand_info = item.get('naverShoppingSearchInfo', {})
                brand = brand_info.get('brandName', '')

                product_id = str(item.get('id', ''))
                if self.store_type == "brand":
                    product_url = f"https://brand.naver.com/{self.store_name}/products/{product_id}"
                else:
                    product_url = f"https://smartstore.naver.com/{self.store_name}/products/{product_id}"

                # 카테고리 정보: 스토어 카테고리 또는 네이버 쇼핑 카테고리
                category_name = self.current_store_category
                if not category_name:
                    # 폴백: 네이버 쇼핑 카테고리
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

                product = ProductInfo(
                    product_id=product_id,
                    product_name=item.get('name', ''),
                    brand=self.store_name,
                    price=item.get('price', 0),
                    sale_price=item.get('salePrice', 0),
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
            clicked = await self.page.evaluate("""
                (targetPage) => {
                    // 숫자만 포함된 a 태그를 모두 수집
                    const allLinks = document.querySelectorAll('a');
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
                        for (const link of paginationGroup) {
                            if (link.num === targetPage) {
                                link.el.click();
                                return true;
                            }
                        }
                    }

                    return false;
                }
            """, target_page)

            if clicked:
                # 페이지 전환 대기
                await asyncio.sleep(2)
                await self.page.evaluate('window.scrollTo(0, 0)')
                await asyncio.sleep(0.5)
                return True

            self.log(f"    ⚠️ 페이지 {target_page} 버튼을 찾지 못함")
            return False

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

        # 카테고리 정보 수집 (DOM 브레드크럼에서 추출) - 페이지 방문 후 항상 시도
        if self.page and not product.extra_info.get('category'):
            try:
                category = await self.page.evaluate("""
                    () => {
                        // 브레드크럼 영역에서 카테고리 추출
                        // 홈 > NEW신작(총 53개) 형태
                        const breadcrumbSelectors = [
                            '[class*="breadcrumb"]',
                            '[class*="Breadcrumb"]',
                            '[class*="_1cW8Nvw5xU"]',  // 네이버 스마트스토어 브레드크럼 클래스
                            'nav[aria-label*="경로"]',
                            '[role="navigation"] ol',
                        ];

                        for (const sel of breadcrumbSelectors) {
                            const container = document.querySelector(sel);
                            if (container) {
                                const links = container.querySelectorAll('a, span, li');
                                const parts = [];
                                for (const el of links) {
                                    let text = el.textContent.trim();
                                    // 불필요한 텍스트 제거
                                    if (text && text !== '>' && text !== '/' &&
                                        !text.includes('다른상품') &&
                                        text.length < 50) {
                                        // 괄호 안 숫자 제거 (총 53개 등)
                                        text = text.replace(/\\(총\\s*\\d+개\\)/g, '').trim();
                                        if (text && !parts.includes(text)) {
                                            parts.push(text);
                                        }
                                    }
                                }
                                if (parts.length > 1) {
                                    // '홈' 제거하고 나머지 반환
                                    const filtered = parts.filter(p => p !== '홈' && p !== 'Home');
                                    return filtered.join('>');
                                }
                            }
                        }

                        // 폴백: 페이지에서 카테고리 드롭다운 텍스트 추출
                        const dropdown = document.querySelector('[class*="category"] button, [class*="Category"] button');
                        if (dropdown) {
                            const text = dropdown.textContent.trim();
                            if (text && !text.includes('다른상품')) {
                                return text.replace(/\\(총\\s*\\d+개\\)/g, '').trim();
                            }
                        }

                        return '';
                    }
                """)

                if category:
                    product.extra_info['category'] = category
                    self.logger.debug(f"카테고리 수집 (DOM): {category}")
            except Exception as e:
                self.logger.debug(f"DOM 카테고리 추출 실패: {e}")

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

        # 상세 설명 수집 (renderContent에서 이미지 + 텍스트 추출)
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

        # 상세 이미지 폴백: content_data가 없으면 DOM에서 추출 시도
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

                        // 상세설명 영역 선택자들
                        const detailSelectors = [
                            '[class*="ProductContent"]',
                            '[class*="product-content"]',
                            '[class*="detail-content"]',
                            '[class*="se-main-container"]',
                            '[class*="se_component"]',
                            'div[id*="detail"]',
                            'div[id*="content"]',
                        ];

                        for (const sel of detailSelectors) {
                            const container = document.querySelector(sel);
                            if (container) {
                                const imgs = container.querySelectorAll('img');
                                for (const img of imgs) {
                                    const src = img.src || img.dataset.src || img.dataset.lazySrc || '';
                                    if (src && src.startsWith('http') &&
                                        !src.includes('data:image') &&
                                        !seen.has(src) &&
                                        !src.includes('logo') &&
                                        !src.includes('icon')) {
                                        seen.add(src);
                                        images.push(src);
                                    }
                                }
                                if (images.length > 0) break;
                            }
                        }

                        // 폴백: 전체 페이지에서 상세 이미지 패턴 찾기
                        if (images.length === 0) {
                            const allImgs = document.querySelectorAll('img');
                            for (const img of allImgs) {
                                const src = img.src || '';
                                // 상세 이미지 패턴 (일정 크기 이상, 상품 이미지가 아닌 것)
                                if (src.startsWith('http') &&
                                    (src.includes('proxy-smartstore') ||
                                     src.includes('esmplus') ||
                                     src.includes('shop-phinf')) &&
                                    !seen.has(src) &&
                                    img.naturalWidth > 300) {
                                    seen.add(src);
                                    images.push(src);
                                }
                            }
                        }

                        return images.slice(0, 50);  // 최대 50개
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
