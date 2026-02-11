"""
무신사 수집기
"""
import asyncio
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

from .base import BaseCollector, ProductInfo, ProductOption

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from config import MusinsaConfig


class MusinsaCollector(BaseCollector):
    """무신사 상품 수집기"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.musinsa_config = MusinsaConfig()

    def parse_url(self, url: str) -> Dict[str, Any]:
        """
        무신사 URL 파싱

        Args:
            url: 무신사 카테고리 URL

        Returns:
            파싱된 정보 (category_id, brand, page 등)
        """
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        # 카테고리 ID 추출
        path_parts = parsed.path.strip('/').split('/')
        category_id = None
        if 'categories' in path_parts:
            idx = path_parts.index('categories')
            if idx + 2 < len(path_parts):
                category_id = path_parts[idx + 2]  # /categories/item/001 -> 001
            elif idx + 1 < len(path_parts):
                category_id = path_parts[idx + 1]

        return {
            "category_id": category_id,
            "brand": query.get("brand", [None])[0],
            "page": int(query.get("page", [1])[0]),
        }

    async def collect_category(self, url: str, start_page: int = 1, end_page: int = None) -> List[ProductInfo]:
        """카테고리 페이지에서 상품 목록 수집 (직접 API 호출 방식)"""
        products = []
        current_page = start_page
        has_next = True

        # URL에서 파라미터 추출
        parsed = urlparse(url)
        query = parse_qs(parsed.query)

        # 카테고리 코드 추출 (URL 경로에서)
        path_parts = parsed.path.strip('/').split('/')
        category_code = None
        if 'category' in path_parts:
            idx = path_parts.index('category')
            if idx + 1 < len(path_parts):
                category_code = path_parts[idx + 1]

        if not category_code:
            self.log("  ⚠️ 카테고리 코드를 찾을 수 없습니다.")
            return products

        # 기본 파라미터 설정
        gf = query.get('gf', ['A'])[0]
        sort_code = query.get('sortCode', [None])[0]  # URL에 없으면 None → API 기본값(추천순) 사용
        page_size = 60  # 무신사 기본 페이지 크기

        sort_display = sort_code if sort_code else '추천순(기본)'
        self.log(f"카테고리 URL: {url}")
        self.log(f"  카테고리: {category_code}, 정렬: {sort_display}, 성별: {gf}")

        # 최초 1회 페이지 방문 (쿠키/세션 획득)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=self.config.PAGE_TIMEOUT)
            await asyncio.sleep(2)
        except Exception as e:
            self.log(f"  ⚠️ 초기 페이지 로드 실패: {e}")

        while has_next:
            # 중지 요청 체크
            if self.should_stop():
                self.log("  ⚠️ 사용자에 의해 수집이 중지되었습니다.")
                break

            self.log(f"  📄 페이지 {current_page} 로딩 중...")

            # seen 계산 (이전 페이지까지 본 상품 수)
            seen = (current_page - 1) * page_size

            # API 직접 호출
            api_url = self._build_api_url(category_code, current_page, page_size, seen, gf, sort_code)

            try:
                response = await self.page.request.get(api_url, headers={
                    'Accept': 'application/json',
                    'Origin': 'https://www.musinsa.com',
                    'Referer': url
                })

                if response.status != 200:
                    self.log(f"  ⚠️ API 응답 오류: {response.status}")
                    break

                plp_data = await response.json()

            except Exception as e:
                self.log(f"  ⚠️ API 호출 실패: {e}")
                break

            if not plp_data or not plp_data.get('data', {}).get('list'):
                self.log(f"  ⚠️ 페이지 {current_page}: API 데이터 없음")
                break

            # 상품 목록 추출
            items = plp_data.get('data', {}).get('list', [])
            self.log(f"  ✓ 페이지 {current_page}: {len(items)}개 상품 발견")

            if len(items) == 0:
                # 더 이상 상품이 없으면 종료
                break

            for item in items:
                product = ProductInfo(
                    product_id=str(item.get('goodsNo', '')),
                    product_name=item.get('goodsName', ''),
                    brand=item.get('brandName', ''),
                    price=item.get('normalPrice', 0),
                    sale_price=item.get('price', 0),
                    image_url=item.get('imageUrl', '') or item.get('goodsImage', ''),
                    url=self.musinsa_config.PRODUCT_URL.format(goods_no=item.get('goodsNo', '')),
                )
                products.append(product)

            # 다음 페이지 확인
            pagination = plp_data.get('data', {}).get('pagination', {})
            total_pages = pagination.get('totalPages', 1)
            total_count = pagination.get('totalCount', 0)
            self.state.total_pages = total_pages

            self.log(f"    (전체: {total_count}개 상품, {total_pages}페이지)")

            if end_page and current_page >= end_page:
                has_next = False
            elif current_page >= total_pages:
                has_next = False
            elif len(items) < page_size:
                # 받은 상품 수가 페이지 크기보다 적으면 마지막 페이지
                has_next = False
            else:
                current_page += 1
                self.state.current_page = current_page
                await self.random_delay()

        return products

    def _build_api_url(self, category: str, page: int, size: int, seen: int, gf: str, sort_code: str = None) -> str:
        """무신사 상품 목록 API URL 생성"""
        params = {
            'category': category,
            'page': page,
            'size': size,
            'seen': seen,
            'gf': gf,
            'caller': 'CATEGORY',
            'seenAds': '',
            'testGroup': ''
        }
        # sortCode가 지정된 경우에만 포함 (미지정 시 API 기본값 = 추천순)
        if sort_code:
            params['sortCode'] = sort_code
        query_str = '&'.join(f"{k}={v}" for k, v in params.items())
        return f"https://api.musinsa.com/api2/dp/v1/plp/goods?{query_str}"

    def _build_page_url(self, base_url: str, page: int) -> str:
        """페이지 URL 생성 (브라우저 네비게이션용 - 현재 미사용)"""
        parsed = urlparse(base_url)
        query = parse_qs(parsed.query)
        query['page'] = [str(page)]

        query_str = '&'.join(f"{k}={v[0]}" for k, v in query.items())
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{query_str}"

    async def collect_product_detail(self, product: ProductInfo) -> ProductInfo:
        """상품 상세 정보 수집"""
        goods_no = product.product_id
        detail_url = product.url

        # 상세 페이지 방문 (DOM 추출 + 쿠키 획득)
        try:
            await self.page.goto(detail_url, wait_until="domcontentloaded", timeout=self.config.PAGE_TIMEOUT)
            await asyncio.sleep(0.5)  # 동적 콘텐츠 로드 대기
        except:
            pass

        # 0. 카테고리 정보 수집 (DOM에서 추출)
        try:
            # 카테고리 컨테이너가 로드될 때까지 대기
            try:
                await self.page.wait_for_selector('[class*="Category__Wrap"]', timeout=3000)
            except:
                pass

            category = await self.page.evaluate("""
                () => {
                    const container = document.querySelector('[class*="Category__Wrap"]');
                    if (!container) return '';

                    const parts = [];
                    const links = container.querySelectorAll('a[class*="CategoryItem"], a[class*="CategoryBrand"]');
                    for (const link of links) {
                        let text = link.textContent.trim();
                        if (text) {
                            parts.push(text);
                        }
                    }

                    return parts.join('>');
                }
            """)
            if category:
                product.extra_info['category'] = category
                self.logger.debug(f"카테고리 수집: {category}")
        except Exception as e:
            self.logger.debug(f"카테고리 수집 실패 [{goods_no}]: {e}")

        # 1~3. API 3개 병렬 호출 (기본정보 + 통계 + 리뷰)
        api_headers = {
            'Accept': 'application/json',
            'Origin': 'https://www.musinsa.com',
            'Referer': detail_url
        }

        async def fetch_info():
            try:
                resp = await self.page.request.get(
                    f"https://goods-detail.musinsa.com/api2/goods/{goods_no}",
                    headers=api_headers
                )
                if resp.status == 200:
                    return await resp.json()
            except Exception as e:
                self.logger.debug(f"기본 정보 API 실패 [{goods_no}]: {e}")
            return None

        async def fetch_stat():
            try:
                resp = await self.page.request.get(
                    f"https://goods-detail.musinsa.com/api2/goods/{goods_no}/stat",
                    headers=api_headers
                )
                if resp.status == 200:
                    return await resp.json()
            except Exception as e:
                self.logger.debug(f"통계 API 실패 [{goods_no}]: {e}")
            return None

        async def fetch_review():
            try:
                resp = await self.page.request.get(
                    f"https://goods.musinsa.com/api2/review/v1/goods/{goods_no}/reviews/summary",
                    headers=api_headers
                )
                if resp.status == 200:
                    return await resp.json()
            except Exception as e:
                self.logger.debug(f"리뷰 API 실패 [{goods_no}]: {e}")
            return None

        info_data, stat_data, review_data = await asyncio.gather(
            fetch_info(), fetch_stat(), fetch_review()
        )

        # 기본 정보 처리
        if info_data:
            d = info_data.get('data', {})
            product.extra_info['style_no'] = d.get('styleNo', '')

            sex = d.get('sex', [])
            product.extra_info['gender'] = ', '.join(sex) if isinstance(sex, list) else str(sex)

            season_year = d.get('seasonYear', '')
            season_code = d.get('season', '')
            season_name = 'SS' if season_code == '1' else 'FW' if season_code == '2' else season_code
            product.extra_info['season'] = f"{season_year} {season_name}".strip()

            if d.get('thumbnailImageUrl'):
                img = d.get('thumbnailImageUrl')
                if img.startswith('/'):
                    img = 'https://image.musinsa.com' + img
                product.image_url = img

            goods_images = d.get('goodsImages', [])
            if goods_images:
                extra_images = []
                for img_data in goods_images:
                    img_url = img_data.get('imageUrl', '')
                    if img_url:
                        if img_url.startswith('/'):
                            img_url = 'https://image.musinsa.com' + img_url
                        extra_images.append(img_url)
                product.extra_info['extra_images'] = extra_images

        # 통계 처리
        if stat_data:
            d = stat_data.get('data', {})
            product.extra_info['view_count'] = d.get('pageViewTotal', 0)
            product.extra_info['sales_count'] = d.get('purchaseTotal', 0)

        # 리뷰 처리
        if review_data:
            d = review_data.get('data', {})
            product.extra_info['review_count'] = d.get('totalCount', 0)
            product.extra_info['rating'] = d.get('satisfactionScore', 0)

        # 4. 상세 설명 영역 로드 (lazy-load 트리거)
        # 상세 설명 영역은 IntersectionObserver로 스크롤 시 렌더링됨
        try:
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)
            await self.page.wait_for_selector('[class*="Contents__StyledInner"]', timeout=3000)
        except:
            pass  # 타임아웃이어도 다른 셀렉터로 시도

        # 5. 상세 설명 이미지 수집 (DOM에서 추출)
        try:
            detail_images = await self.page.evaluate("""
                () => {
                    // 이미지 URL 추출 함수 (data-src 우선, thumbnails 경로 제거)
                    const getImageUrl = (img) => {
                        // 우선순위: data-src > data-fallback-src > src
                        let url = img.getAttribute('data-src')
                               || img.getAttribute('data-fallback-src')
                               || img.src;

                        if (!url) return null;

                        // // 로 시작하면 https: 추가
                        if (url.startsWith('//')) {
                            url = 'https:' + url;
                        }

                        // thumbnails 경로 제거 (원본 이미지 URL 사용)
                        url = url.replace('/thumbnails/images/', '/images/');

                        return url;
                    };

                    // 방법 1: 컨테이너에서 alt="content-img-XX" 패턴 이미지 찾기 (도메인 무관)
                    const containers = [
                        '[class*="Contents__StyledInner"]',
                        '[class*="product-detail"]',
                        '.product_detail_description',
                        '[class*="ProductDetailContent"]',
                        '[class*="detail-content"]'
                    ];

                    let result = [];
                    for (const selector of containers) {
                        const container = document.querySelector(selector);
                        if (container) {
                            // alt="content-img-XX" 패턴의 상품 상세 이미지 (외부 도메인 포함)
                            const contentImgs = Array.from(container.querySelectorAll('img[alt^="content-img"]'));
                            if (contentImgs.length > 0) {
                                result = contentImgs
                                    .map(img => getImageUrl(img))
                                    .filter(url => url && url.startsWith('http'));
                                if (result.length > 0) break;
                            }
                        }
                    }

                    // 방법 2: content-img 패턴이 없으면 무신사/msscdn 도메인 이미지 찾기
                    if (result.length === 0) {
                        for (const selector of containers) {
                            const container = document.querySelector(selector);
                            if (container) {
                                const imgs = Array.from(container.querySelectorAll('img'));
                                result = imgs
                                    .map(img => getImageUrl(img))
                                    .filter(url => {
                                        if (!url || !url.startsWith('http')) return false;
                                        if (!url.includes('musinsa.com') && !url.includes('msscdn.net')) return false;
                                        // 공통/배너 이미지 제외
                                        if (url.includes('/display/images/common/')) return false;
                                        if (url.includes('/display/images/') && !url.includes('/prd_img/') && !url.includes('/detail_')) return false;
                                        return true;
                                    });
                                if (result.length > 0) break;
                            }
                        }
                    }

                    // 방법 3: 컨테이너에서 못 찾으면 URL 패턴으로 상세 이미지 찾기
                    if (result.length === 0) {
                        const patternImgs = Array.from(document.querySelectorAll('img')).filter(img => {
                            const url = getImageUrl(img) || '';
                            return url.includes('/prd_img/') || url.includes('/detail_');
                        });
                        result = patternImgs
                            .map(img => getImageUrl(img))
                            .filter(url => url && url.startsWith('http'));
                    }

                    return result;
                }
            """)
            if detail_images:
                product.extra_info['detail_images'] = detail_images
                self.logger.debug(f"상세 이미지 {len(detail_images)}개 수집")
        except Exception as e:
            self.logger.debug(f"상세 이미지 수집 실패 [{goods_no}]: {e}")

        # 5-1. 폴백: DOM에서 못 찾으면 JavaScript 전역 객체에서 이미지 추출
        if not product.extra_info.get('detail_images'):
            try:
                fallback_images = await self.page.evaluate("""
                    () => {
                        // window.__MSS__ 또는 window.__MSS_FE__에서 goodsContents 추출
                        let htmlContent = null;

                        if (window.__MSS__?.product?.state?.goodsContents) {
                            htmlContent = window.__MSS__.product.state.goodsContents;
                        } else if (window.__MSS_FE__?.product?.state?.goodsContents) {
                            htmlContent = window.__MSS_FE__.product.state.goodsContents;
                        } else {
                            const nextData = document.getElementById('__NEXT_DATA__');
                            if (nextData) {
                                try {
                                    const data = JSON.parse(nextData.textContent);
                                    const pageProps = data?.props?.pageProps;
                                    if (pageProps?.goodsContents) {
                                        htmlContent = pageProps.goodsContents;
                                    } else if (pageProps?.dehydratedState?.queries) {
                                        for (const query of pageProps.dehydratedState.queries) {
                                            if (query?.state?.data?.data?.goodsContents) {
                                                htmlContent = query.state.data.data.goodsContents;
                                                break;
                                            }
                                        }
                                    }
                                } catch (e) {}
                            }
                        }

                        if (!htmlContent) return [];

                        // HTML에서 이미지 URL 추출
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(htmlContent, 'text/html');
                        const imgs = doc.querySelectorAll('img');
                        const result = [];

                        imgs.forEach(img => {
                            let url = img.getAttribute('src') || '';
                            if (url.startsWith('//')) {
                                url = 'https:' + url;
                            }
                            // thumbnails 경로 제거
                            url = url.replace('/thumbnails/images/', '/images/');
                            if (url && url.startsWith('http')) {
                                result.push(url);
                            }
                        });

                        return result;
                    }
                """)
                if fallback_images:
                    product.extra_info['detail_images'] = fallback_images
                    self.logger.debug(f"상세 이미지 수집 (폴백): {len(fallback_images)}개")
            except Exception as e:
                self.logger.debug(f"상세 이미지 폴백 수집 실패 [{goods_no}]: {e}")

        # 6. 상세 설명 텍스트 수집 (DOM에서 추출)
        try:
            description_text = await self.page.evaluate("""
                () => {
                    // 상세 설명 컨테이너 셀렉터
                    const containers = [
                        '[class*="Contents__StyledInner"]',
                        '[class*="product-detail"]',
                        '.product_detail_description',
                        '[class*="ProductDetailContent"]',
                        '[class*="detail-content"]'
                    ];

                    for (const selector of containers) {
                        const container = document.querySelector(selector);
                        if (container) {
                            // innerText로 보이는 텍스트만 추출 (줄바꿈 유지)
                            let text = container.innerText || '';
                            // 연속 공백/줄바꿈 정리
                            text = text.replace(/\\n\\s*\\n/g, '\\n').trim();
                            if (text.length > 0) {
                                return text;
                            }
                        }
                    }
                    return '';
                }
            """)
            if description_text:
                product.extra_info['description'] = description_text
                self.logger.debug(f"상세 설명 텍스트 수집: {len(description_text)}자")
        except Exception as e:
            self.logger.debug(f"상세 설명 텍스트 수집 실패 [{goods_no}]: {e}")

        # 6-1. 폴백: DOM에서 못 찾으면 JavaScript 전역 객체에서 추출
        if not product.extra_info.get('description'):
            try:
                fallback_description = await self.page.evaluate("""
                    () => {
                        // window.__MSS__ 또는 window.__MSS_FE__에서 goodsContents 추출
                        let htmlContent = null;

                        // 방법 1: __MSS__.product.state.goodsContents
                        if (window.__MSS__?.product?.state?.goodsContents) {
                            htmlContent = window.__MSS__.product.state.goodsContents;
                        }
                        // 방법 2: __MSS_FE__.product.state.goodsContents
                        else if (window.__MSS_FE__?.product?.state?.goodsContents) {
                            htmlContent = window.__MSS_FE__.product.state.goodsContents;
                        }
                        // 방법 3: __NEXT_DATA__에서 추출
                        else {
                            const nextData = document.getElementById('__NEXT_DATA__');
                            if (nextData) {
                                try {
                                    const data = JSON.parse(nextData.textContent);
                                    const pageProps = data?.props?.pageProps;
                                    if (pageProps?.goodsContents) {
                                        htmlContent = pageProps.goodsContents;
                                    } else if (pageProps?.dehydratedState?.queries) {
                                        // React Query 캐시에서 찾기
                                        for (const query of pageProps.dehydratedState.queries) {
                                            if (query?.state?.data?.data?.goodsContents) {
                                                htmlContent = query.state.data.data.goodsContents;
                                                break;
                                            }
                                        }
                                    }
                                } catch (e) {}
                            }
                        }

                        if (!htmlContent) return '';

                        // HTML을 텍스트로 변환
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(htmlContent, 'text/html');
                        let text = doc.body.innerText || '';
                        text = text.replace(/\\n\\s*\\n/g, '\\n').trim();
                        return text;
                    }
                """)
                if fallback_description:
                    product.extra_info['description'] = fallback_description
                    self.logger.debug(f"상세 설명 텍스트 수집 (폴백): {len(fallback_description)}자")
            except Exception as e:
                self.logger.debug(f"상세 설명 폴백 수집 실패 [{goods_no}]: {e}")

        return product

    async def collect_options(self, product: ProductInfo) -> List[ProductOption]:
        """상품 옵션 수집 - API + DOM 병행 (품절 여부는 DOM에서 추출)"""
        goods_no = product.product_id
        detail_url = product.url
        options = []

        try:
            # 1. 드롭다운에서 품절 정보 추출 (1차 옵션 선택 후 2차 드롭다운 확인)
            sold_out_set = set()
            try:
                all_dropdowns = await self.page.query_selector_all('[data-mds="DropdownTriggerInput"]')
                if not all_dropdowns:
                    all_dropdowns = await self.page.query_selector_all('input[placeholder="사이즈"], input[placeholder="색상"]')

                self.logger.debug(f"드롭다운 {len(all_dropdowns)}개 발견")

                if len(all_dropdowns) >= 2:
                    # 2개 이상 드롭다운: 1차 옵션 선택 후 2차 드롭다운에서 품절 확인
                    first_dropdown = all_dropdowns[0]
                    await first_dropdown.scroll_into_view_if_needed()
                    await first_dropdown.click()
                    await asyncio.sleep(0.5)

                    # 1차 옵션 첫 번째 항목 선택
                    first_option = await self.page.query_selector('[data-mds="StaticDropdownMenuItem"]')
                    if first_option:
                        await first_option.click()
                        await asyncio.sleep(0.5)

                        # 2차 드롭다운 찾기 (placeholder="사이즈"로 직접 찾기)
                        size_dropdown = await self.page.query_selector('input[placeholder="사이즈"]')
                        if size_dropdown:
                            await size_dropdown.scroll_into_view_if_needed()
                            await size_dropdown.click()
                            await asyncio.sleep(0.5)

                            # 2차 드롭다운에서 품절 옵션 추출
                            dropdown_soldout = await self.page.evaluate("""
                                () => {
                                    const soldOutSet = new Set();
                                    const optionItems = document.querySelectorAll('[data-mds="StaticDropdownMenuItem"]');
                                    for (const item of optionItems) {
                                        const text = item.textContent || '';
                                        const hasSoldOutText = text.includes('(품절)') || text.includes('품절');
                                        if (hasSoldOutText) {
                                            const optionValue = text.replace(/\\s*\\(품절\\).*$/, '').trim();
                                            if (optionValue) {
                                                soldOutSet.add(optionValue);
                                            }
                                        }
                                    }
                                    return Array.from(soldOutSet);
                                }
                            """)

                            if dropdown_soldout:
                                sold_out_set.update(dropdown_soldout)
                                self.logger.debug(f"2차 드롭다운 품절: {dropdown_soldout}")

                            await self.page.keyboard.press('Escape')
                            await asyncio.sleep(0.2)
                    else:
                        await self.page.keyboard.press('Escape')

                elif len(all_dropdowns) == 1:
                    # 1개 드롭다운: 직접 품절 확인
                    dropdown = all_dropdowns[0]
                    await dropdown.scroll_into_view_if_needed()
                    await dropdown.click()
                    await asyncio.sleep(0.5)

                    dropdown_soldout = await self.page.evaluate("""
                        () => {
                            const soldOutSet = new Set();
                            const optionItems = document.querySelectorAll('[data-mds="StaticDropdownMenuItem"]');
                            for (const item of optionItems) {
                                const text = item.textContent || '';
                                const hasSoldOutText = text.includes('(품절)') || text.includes('품절');
                                if (hasSoldOutText) {
                                    const optionValue = text.replace(/\\s*\\(품절\\).*$/, '').trim();
                                    if (optionValue) {
                                        soldOutSet.add(optionValue);
                                    }
                                }
                            }
                            return Array.from(soldOutSet);
                        }
                    """)

                    if dropdown_soldout:
                        sold_out_set.update(dropdown_soldout)

                    await self.page.keyboard.press('Escape')
                    await asyncio.sleep(0.2)

                if sold_out_set:
                    self.log(f"    품절 옵션: {len(sold_out_set)}개 ({', '.join(list(sold_out_set)[:5])}{'...' if len(sold_out_set) > 5 else ''})")

            except Exception as e:
                self.log(f"    ⚠️ 품절 정보 추출 실패: {e}")

            # 2. API에서 옵션 목록 가져오기
            options_url = f"https://goods-detail.musinsa.com/api2/goods/{goods_no}/options"
            response = await self.page.request.get(options_url, headers={
                'Accept': 'application/json',
                'Origin': 'https://www.musinsa.com',
                'Referer': detail_url
            })

            if response.status == 200:
                data = await response.json()
                api_data = data.get('data', {})

                # basic에서 옵션값별 sequence 맵 생성 (정렬용)
                sequence_map = {}  # {옵션값: sequence}
                basic_list = api_data.get('basic', [])
                for basic in basic_list:
                    for opt_val in basic.get('optionValues', []):
                        name = opt_val.get('name', '')
                        seq = opt_val.get('sequence', 0)
                        sequence_map[name] = seq

                # optionItems에서 직접 옵션 조합 추출
                option_items = api_data.get('optionItems', [])

                # optionItems를 sequence 순서로 정렬
                def get_sort_key(item):
                    opt_values = item.get('optionValues', [])
                    keys = []
                    for ov in opt_values:
                        name = ov.get('name', '')
                        keys.append(sequence_map.get(name, 999))
                    return tuple(keys)

                option_items = sorted(option_items, key=get_sort_key)

                if option_items:
                    for item in option_items:
                        # API 기본 정보
                        is_deleted = item.get('isDeleted', False)
                        additional_price = item.get('price', 0)

                        # 옵션값에서 색상/사이즈 추출 + 원본 option_data 보존
                        opt_values = item.get('optionValues', [])
                        color = ''
                        size = ''
                        option_data = {}

                        for ov in opt_values:
                            opt_name = ov.get('optionName', '').strip()
                            opt_name_lower = opt_name.lower()
                            value = ov.get('name', '')

                            # 원본 이름-값 쌍 보존
                            option_data[opt_name] = value

                            if opt_name_lower == 'c' or '색상' in opt_name_lower or 'color' in opt_name_lower or '컬러' in opt_name_lower:
                                color = value
                            elif opt_name_lower == 's' or '사이즈' in opt_name_lower or 'size' in opt_name_lower:
                                size = value
                            else:
                                # 기타 옵션은 사이즈로 처리 (단일 옵션 상품)
                                if not size:
                                    size = value

                        # 품절 여부: DOM에서 감지된 품절 목록과 대조
                        is_sold_out = is_deleted  # 기본값: API의 isDeleted
                        # DOM에서 감지된 품절 옵션과 비교
                        if size and size in sold_out_set:
                            is_sold_out = True
                        if color and color in sold_out_set:
                            is_sold_out = True

                        options.append(ProductOption(
                            color=color,
                            size=size,
                            additional_price=additional_price,
                            stock=0 if is_sold_out else 100,
                            sold_out=is_sold_out,
                            option_data=option_data,
                        ))

                    self.logger.debug(f"옵션 수집 완료 [{goods_no}]: {len(options)}개")

                # optionItems가 없으면 basic에서 추출 (폴백)
                elif api_data.get('basic'):
                    basic_list = api_data.get('basic', [])
                    for basic in basic_list:
                        for opt_val in basic.get('optionValues', []):
                            is_deleted = opt_val.get('isDeleted', False)
                            name = opt_val.get('name', '')
                            group_name = basic.get('name', '').strip()
                            group_name_lower = group_name.lower()

                            # 원본 이름-값 쌍 보존
                            option_data = {group_name: name}

                            color = ''
                            size = ''
                            if group_name_lower == 'c' or '색상' in group_name_lower or 'color' in group_name_lower or '컬러' in group_name_lower:
                                color = name
                            elif group_name_lower == 's' or '사이즈' in group_name_lower or 'size' in group_name_lower:
                                size = name
                            else:
                                color, size = self._parse_option_name(name)

                            # 품절 여부: DOM에서 감지
                            is_sold_out = is_deleted
                            if size and size in sold_out_set:
                                is_sold_out = True
                            if color and color in sold_out_set:
                                is_sold_out = True

                            options.append(ProductOption(
                                color=color,
                                size=size,
                                additional_price=0,
                                stock=0 if is_sold_out else 100,
                                sold_out=is_sold_out,
                                option_data=option_data,
                            ))

        except Exception as e:
            self.logger.debug(f"옵션 API 실패 [{goods_no}]: {e}")

        return options

    def _parse_option_name(self, name: str) -> tuple:
        """
        옵션 이름에서 색상과 사이즈 분리

        Args:
            name: 옵션 이름 (예: "블랙 M", "네이비 XL")

        Returns:
            (색상, 사이즈) 튜플
        """
        parts = name.strip().rsplit(' ', 1)
        if len(parts) == 2:
            color, size = parts
            # 사이즈 패턴 확인
            if re.match(r'^(XS|S|M|L|XL|XXL|2XL|3XL|FREE|\d+)$', size, re.IGNORECASE):
                return color, size
        return '', name


def is_musinsa_url(url: str) -> bool:
    """무신사 URL인지 확인"""
    parsed = urlparse(url)
    return 'musinsa.com' in parsed.netloc
