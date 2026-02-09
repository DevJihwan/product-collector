"""
다이소몰 수집기
"""
import asyncio
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs, urlencode

from .base import BaseCollector, ProductInfo, ProductOption

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from config import DaisoConfig


class DaisoCollector(BaseCollector):
    """다이소몰 상품 수집기"""

    def __init__(self, headless: bool = True):
        super().__init__(headless)
        self.daiso_config = DaisoConfig()

    def parse_url(self, url: str) -> Dict[str, Any]:
        """
        다이소몰 URL 파싱

        Args:
            url: 다이소몰 카테고리 URL
                예: /ds/exhCtgr/C208/CTGR_00014/CTGR_00057

        Returns:
            파싱된 정보 (large_ctgr, middle_ctgr 등)
        """
        parsed = urlparse(url)
        path_parts = parsed.path.strip('/').split('/')

        result = {
            "large_ctgr": None,
            "middle_ctgr": None,
            "small_ctgr": None,
        }

        # /ds/exhCtgr/C208/CTGR_00014/CTGR_00057 형태
        if 'exhCtgr' in path_parts:
            idx = path_parts.index('exhCtgr')
            remaining = path_parts[idx + 1:]

            for part in remaining:
                if part.startswith('CTGR_'):
                    if not result["large_ctgr"]:
                        result["large_ctgr"] = part
                    elif not result["middle_ctgr"]:
                        result["middle_ctgr"] = part
                    else:
                        result["small_ctgr"] = part

        return result

    async def collect_category(self, url: str, start_page: int = 1, end_page: int = None) -> List[ProductInfo]:
        """카테고리 페이지에서 상품 목록 수집 (API 기반)"""
        products = []
        current_page = start_page
        has_next = True

        # URL 파싱
        url_info = self.parse_url(url)
        large_ctgr = url_info.get("large_ctgr", "")
        middle_ctgr = url_info.get("middle_ctgr", "")
        small_ctgr = url_info.get("small_ctgr", "")

        self.log(f"카테고리 URL: {url}")
        self.log(f"  대분류: {large_ctgr}, 중분류: {middle_ctgr}")

        # 최초 1회 페이지 방문 (쿠키/세션 획득)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=self.config.PAGE_TIMEOUT)
            await asyncio.sleep(3)
        except Exception as e:
            self.log(f"  ⚠️ 초기 페이지 로드 실패: {e}")

        while has_next:
            # 중지 요청 체크
            if self.should_stop():
                self.log("  ⚠️ 사용자에 의해 수집이 중지되었습니다.")
                break

            self.log(f"  📄 페이지 {current_page} 로딩 중...")

            # API 호출
            api_url = self._build_search_api_url(
                page=current_page,
                large_ctgr=large_ctgr,
                middle_ctgr=middle_ctgr,
                small_ctgr=small_ctgr
            )

            try:
                # page.evaluate로 fetch 호출 (동일 도메인 요청)
                api_data = await self.page.evaluate(f"""
                    async () => {{
                        const response = await fetch("{api_url}");
                        return await response.json();
                    }}
                """)

                # returnCode가 1(성공) 또는 status가 200이면 성공
                if not api_data:
                    self.log(f"  ⚠️ API 응답 없음")
                    break

                return_code = api_data.get('returnCode')
                status_code = api_data.get('status')
                if return_code not in [1, '1', '000'] and status_code != 200:
                    self.log(f"  ⚠️ API 응답 오류: returnCode={return_code}, status={status_code}")
                    break

            except Exception as e:
                self.log(f"  ⚠️ API 호출 실패: {e}")
                break

            # 상품 목록 추출
            result_set = api_data.get('resultSet', {})
            results = result_set.get('result', [])

            # result[1]에 상품 목록이 있음
            product_result = None
            for r in results:
                if 'resultDocuments' in r:
                    product_result = r
                    break

            if not product_result:
                self.log(f"  ⚠️ 페이지 {current_page}: 상품 데이터 없음")
                break

            items = product_result.get('resultDocuments', [])
            total_size = product_result.get('totalSize', 0)

            self.log(f"  ✓ 페이지 {current_page}: {len(items)}개 상품 발견")

            if len(items) == 0:
                break

            for item in items:
                # 이미지 URL 생성
                img_path = item.get('pdImgUrl', '')
                image_url = f"{self.daiso_config.CDN_URL}{img_path}" if img_path else ""

                product = ProductInfo(
                    product_id=str(item.get('pdNo', '')),
                    product_name=item.get('pdNm', '') or item.get('exhPdNm', ''),
                    brand=self._parse_brand(item.get('brndNm', '')),
                    price=self._parse_price(item.get('pdPrc', '')),
                    sale_price=self._parse_price(item.get('pdPrc', '')),  # 다이소는 단일 가격
                    image_url=image_url,
                    url=self.daiso_config.PRODUCT_URL.format(pd_no=item.get('pdNo', '')),
                    extra_info={
                        "category_large": item.get('exhLargeCtgrNm', ''),
                        "category_middle": item.get('exhMiddleCtgrNm', ''),
                        "category_small": item.get('exhSmallCtgrNm', ''),
                        "rating": item.get('avgStscVal', ''),
                        "review_count": item.get('revwCnt', ''),
                        "sold_out": item.get('soldOutYn', 'N') == 'Y',
                        "has_option": item.get('optPdYn', 'N') == 'Y',
                    }
                )
                products.append(product)

            # 페이지네이션 확인
            total_pages = (total_size + self.daiso_config.ITEMS_PER_PAGE - 1) // self.daiso_config.ITEMS_PER_PAGE
            self.state.total_pages = total_pages

            self.log(f"    (전체: {total_size}개 상품, {total_pages}페이지)")

            if end_page and current_page >= end_page:
                has_next = False
            elif current_page >= total_pages:
                has_next = False
            elif len(items) < self.daiso_config.ITEMS_PER_PAGE:
                has_next = False
            else:
                current_page += 1
                self.state.current_page = current_page
                await self.random_delay()

        return products

    def _build_search_api_url(self, page: int, large_ctgr: str, middle_ctgr: str = "",
                               small_ctgr: str = "") -> str:
        """상품 검색 API URL 생성"""
        params = {
            'searchTerm': '',
            'searchQuery': '',
            'pageNum': page,
            'brndCd': '',
            'cntPerPage': self.daiso_config.ITEMS_PER_PAGE,
            'userId': '',
            'newPdYn': '',
            'massOrPsblYn': '',
            'pkupOrPsblYn': '',
            'fdrmOrPsblYn': '',
            'quickOrPsblYn': '',
            'searchSort': '',
            'isCategory': '1',
            'largeExhCtgrNo': large_ctgr,
        }

        if middle_ctgr:
            params['exhCtgrNo'] = middle_ctgr

        query_str = urlencode(params)
        return f"{self.daiso_config.SEARCH_API}?{query_str}"

    def _parse_brand(self, brand_str: str) -> str:
        """브랜드 문자열 파싱 (예: '메디필>00047>메디필' → '메디필')"""
        if not brand_str:
            return ""
        parts = brand_str.split('>')
        return parts[0].strip() if parts else brand_str

    def _parse_price(self, price_str: str) -> int:
        """가격 문자열 파싱"""
        if not price_str:
            return 0
        try:
            # 숫자만 추출
            digits = re.sub(r'[^\d]', '', str(price_str))
            return int(digits) if digits else 0
        except:
            return 0

    async def collect_product_detail(self, product: ProductInfo) -> ProductInfo:
        """상품 상세 정보 수집"""
        pd_no = product.product_id
        detail_url = product.url

        try:
            # 상세 페이지 방문
            await self.page.goto(detail_url, wait_until="domcontentloaded", timeout=self.config.PAGE_TIMEOUT)
            await asyncio.sleep(2)

            # 1단계: 기본 정보 추출 (카테고리, 썸네일, 상세 이미지)
            detail_info = await self.page.evaluate("""
                () => {
                    const result = {
                        title: '',
                        category: '',
                        thumbnail_images: [],
                        detail_images: []
                    };

                    // 1. 브레드크럼 (카테고리 경로) 추출
                    const breadcrumbSelectors = ['.product-crumb', '.el-breadcrumb', '.crumbs'];
                    for (const sel of breadcrumbSelectors) {
                        const container = document.querySelector(sel);
                        if (container) {
                            const items = container.querySelectorAll('a, .el-breadcrumb__item span');
                            const categories = [];
                            items.forEach(item => {
                                const text = item.textContent.trim();
                                if (text && text.length < 20 && !text.includes('>')) {
                                    categories.push(text);
                                }
                            });
                            if (categories.length >= 2) {
                                result.category = categories.join('>');
                                break;
                            }
                        }
                    }

                    // 2. 상품명
                    const titleSelectors = ['.product-name', '.prd-name', 'h1.title', 'h1', '.goods-name'];
                    for (const sel of titleSelectors) {
                        const el = document.querySelector(sel);
                        if (el && el.textContent.trim().length > 2) {
                            result.title = el.textContent.trim();
                            break;
                        }
                    }

                    // 3. 썸네일 이미지
                    const seenUrls = new Set();
                    const thumbBtnImgs = document.querySelectorAll('.el-button img');
                    thumbBtnImgs.forEach(img => {
                        let src = img.src || img.getAttribute('data-src') || '';
                        if (src.includes('/dims/')) {
                            src = src.split('/dims/')[0];
                        } else if (src.includes('?')) {
                            src = src.split('?')[0];
                        }
                        if (src && src.includes('cdn.daisomall') && src.includes('/file/PD/') && !seenUrls.has(src)) {
                            seenUrls.add(src);
                            result.thumbnail_images.push(src);
                        }
                    });

                    if (result.thumbnail_images.length === 0) {
                        const goodsSwiperImgs = document.querySelectorAll('.goods-swiper-wrap .swiper-slide:not(.swiper-slide-duplicate) img');
                        goodsSwiperImgs.forEach(img => {
                            let src = img.src || img.getAttribute('data-src') || '';
                            if (src.includes('/dims/')) {
                                src = src.split('/dims/')[0];
                            } else if (src.includes('?')) {
                                src = src.split('?')[0];
                            }
                            if (src && src.includes('cdn.daisomall') && src.includes('/file/PD/') && !seenUrls.has(src)) {
                                seenUrls.add(src);
                                result.thumbnail_images.push(src);
                            }
                        });
                    }

                    // 4. 상세 설명 이미지 (.editor-content 내부)
                    const editorImgs = document.querySelectorAll('.editor-content img, .editor-area img');
                    editorImgs.forEach(img => {
                        let src = img.src || img.getAttribute('data-src') || '';
                        if (src.includes('/dims/')) {
                            src = src.split('/dims/')[0];
                        } else if (src.includes('?')) {
                            src = src.split('?')[0];
                        }
                        if (src && src.includes('cdn.daisomall') && src.includes('/file/PD/') && !seenUrls.has(src)) {
                            seenUrls.add(src);
                            result.detail_images.push(src);
                        }
                    });

                    return result;
                }
            """)

            # 2단계: '상품정보' 탭 클릭하여 상품정보 제공 고시 추출
            await self.page.evaluate("""
                () => {
                    // '상품정보' 탭 찾아서 클릭
                    const tabs = document.querySelectorAll('.el-tabs__item, [role="tab"]');
                    for (const tab of tabs) {
                        if (tab.textContent.trim().includes('상품정보')) {
                            tab.click();
                            return true;
                        }
                    }
                    return false;
                }
            """)
            await asyncio.sleep(0.5)  # 탭 전환 대기

            # 3단계: 상품정보 제공 고시 테이블 추출
            product_info_table = await self.page.evaluate("""
                () => {
                    const result = {};

                    // .tab-cont.info 또는 상품정보 제공 고시 테이블 찾기
                    const infoContainers = document.querySelectorAll('.tab-cont.info, [class*="info"]');
                    for (const container of infoContainers) {
                        const text = container.textContent;
                        if (text.includes('상품정보 제공 고시') || text.includes('제조국')) {
                            const rows = container.querySelectorAll('table tr');
                            rows.forEach(row => {
                                const th = row.querySelector('th');
                                const td = row.querySelector('td');
                                if (th && td) {
                                    let key = th.textContent.trim();
                                    let value = td.textContent.trim();
                                    // 번호 제거 (예: "1. 내용물의 용량" → "내용물의 용량")
                                    key = key.replace(/^\\d+\\.\\s*/, '');
                                    if (key && value && value !== '상세페이지 참조') {
                                        result[key] = value;
                                    }
                                }
                            });
                            break;
                        }
                    }

                    return result;
                }
            """)

            # 상세 정보 업데이트
            if detail_info.get('title') and not product.product_name:
                product.product_name = detail_info['title']

            # 카테고리 업데이트
            if detail_info.get('category'):
                product.extra_info['category'] = detail_info['category']

            # 썸네일 이미지 처리: 첫 번째는 image_url, 나머지는 extra_images
            thumbnails = detail_info.get('thumbnail_images', [])
            if thumbnails:
                product.image_url = thumbnails[0]
                if len(thumbnails) > 1:
                    product.extra_info['extra_images'] = thumbnails[1:]

            # 상세 설명 이미지
            product.extra_info['detail_images'] = detail_info.get('detail_images', [])

            # 상품정보 제공 고시 (제조국 등)
            product.extra_info['product_info'] = product_info_table

            # description 문자열 생성 (엑셀 출력용)
            if product_info_table:
                desc_lines = [f"{k}: {v}" for k, v in product_info_table.items()]
                product.extra_info['description'] = "\n".join(desc_lines)

            thumb_count = len(thumbnails)
            extra_count = len(thumbnails) - 1 if thumbnails else 0
            detail_img_count = len(detail_info.get('detail_images', []))
            info_count = len(product_info_table)
            self.log(f"  상품 {pd_no}: 썸네일 {thumb_count}개, 상세이미지 {detail_img_count}개, 상품정보 {info_count}개")

        except Exception as e:
            self.log(f"  ⚠️ 상품 상세 수집 실패 [{pd_no}]: {e}")

        return product

    async def collect_options(self, product: ProductInfo) -> List[ProductOption]:
        """상품 옵션 수집"""
        options = []

        # 옵션 상품이 아니면 기본 옵션 반환
        if not product.extra_info.get('has_option', False):
            options.append(ProductOption(
                color="",
                size="기본",
                additional_price=0,
                stock=100,
                sold_out=product.extra_info.get('sold_out', False),
                option_data={"옵션": "기본"}
            ))
            return options

        try:
            # DOM에서 옵션 추출
            option_data = await self.page.evaluate("""
                () => {
                    const options = [];

                    // 옵션 select 박스
                    const selects = document.querySelectorAll('select[class*="option"], select[name*="option"]');
                    selects.forEach(select => {
                        const opts = select.querySelectorAll('option');
                        opts.forEach(opt => {
                            const text = opt.textContent.trim();
                            const value = opt.value;
                            if (text && value && text !== '선택하세요' && text !== '옵션선택') {
                                options.push({
                                    name: text,
                                    value: value,
                                    disabled: opt.disabled,
                                    soldOut: text.includes('품절') || opt.disabled
                                });
                            }
                        });
                    });

                    // 옵션 버튼 형태
                    const optionBtns = document.querySelectorAll('[class*="option"] button, [class*="option"] li');
                    optionBtns.forEach(btn => {
                        const text = btn.textContent.trim();
                        if (text && text.length < 50) {
                            const isSoldOut = btn.classList.contains('sold-out') ||
                                             btn.classList.contains('disabled') ||
                                             btn.disabled ||
                                             text.includes('품절');
                            options.push({
                                name: text,
                                value: text,
                                disabled: isSoldOut,
                                soldOut: isSoldOut
                            });
                        }
                    });

                    return options;
                }
            """)

            for opt in option_data:
                options.append(ProductOption(
                    color="",
                    size=opt.get('name', ''),
                    additional_price=0,
                    stock=0 if opt.get('soldOut', False) else 100,
                    sold_out=opt.get('soldOut', False),
                    option_data={"옵션": opt.get('name', '')}
                ))

            if not options:
                # 옵션이 없으면 기본 옵션
                options.append(ProductOption(
                    color="",
                    size="기본",
                    additional_price=0,
                    stock=100,
                    sold_out=product.extra_info.get('sold_out', False),
                    option_data={"옵션": "기본"}
                ))

        except Exception as e:
            self.log(f"  ⚠️ 옵션 수집 실패 [{product.product_id}]: {e}")
            options.append(ProductOption(
                color="",
                size="기본",
                additional_price=0,
                stock=100,
                sold_out=False,
                option_data={"옵션": "기본"}
            ))

        return options
