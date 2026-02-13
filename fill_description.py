"""
무신사 엑셀 파일의 빈 Description 보완 스크립트
"""
import asyncio
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys

# 출력 버퍼링 비활성화
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

# 프로젝트 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright
from config import CollectorConfig


class DescriptionFiller:
    """Description 보완 클래스"""

    def __init__(self, input_file: str, output_file: str = None):
        self.input_file = Path(input_file)
        self.output_file = Path(output_file) if output_file else self.input_file.parent / f"{self.input_file.stem}_filled.xlsx"
        self.config = CollectorConfig()
        self.browser = None
        self.page = None
        self.playwright = None

        # 진행 상황 저장 파일
        self.progress_file = self.input_file.parent / "fill_progress.json"

    async def setup_browser(self):
        """브라우저 설정"""
        print("브라우저 시작 중...")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.context = await self.browser.new_context(
            user_agent=self.config.USER_AGENT,
            viewport={"width": 1920, "height": 1080}
        )
        self.page = await self.context.new_page()
        print("브라우저 준비 완료")

    async def close_browser(self):
        """브라우저 종료"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("브라우저 종료")

    async def collect_description(self, url: str) -> str:
        """상품 URL에서 description 수집 (폴백 로직 포함)"""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(1)

            # 스크롤하여 lazy-load 트리거
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(1)

            # JavaScript 전역 객체에서 추출 (가장 안정적)
            description = await self.page.evaluate("""
                () => {
                    const state = window.__MSS__?.product?.state
                               || window.__MSS_FE__?.product?.state
                               || {};

                    // specDesc (상세 스펙 설명)
                    if (state.specDesc) {
                        return state.specDesc.trim();
                    }

                    // mdOpinion (MD 의견)
                    if (state.mdOpinion) {
                        return state.mdOpinion.trim();
                    }

                    // goodsContents (HTML → 텍스트)
                    let htmlContent = state.goodsContents;
                    if (!htmlContent) {
                        const nextData = document.getElementById('__NEXT_DATA__');
                        if (nextData) {
                            try {
                                const data = JSON.parse(nextData.textContent);
                                const pageProps = data?.props?.pageProps;
                                htmlContent = pageProps?.goodsContents;
                                if (!htmlContent && pageProps?.dehydratedState?.queries) {
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

                    if (htmlContent) {
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(htmlContent, 'text/html');
                        return (doc.body.innerText || '').trim();
                    }

                    return '';
                }
            """)

            return description or ""

        except Exception as e:
            print(f"  ⚠️ 수집 실패: {e}")
            return ""

    async def run(self, batch_size: int = 100, start_from: int = 0):
        """메인 실행"""
        print(f"=== Description 보완 시작 ===")
        print(f"입력 파일: {self.input_file}")
        print(f"출력 파일: {self.output_file}")

        # 엑셀 파일 읽기
        print("\n엑셀 파일 로딩 중...")
        df = pd.read_excel(self.input_file)
        print(f"총 행 수: {len(df):,}")

        # Description이 비어있는 고유 Product_SKU 찾기
        empty_mask = df['Description'].isna() | (df['Description'] == '')
        empty_skus = df.loc[empty_mask, 'Product_SKU'].unique().tolist()
        print(f"Description이 비어있는 고유 상품 수: {len(empty_skus):,}")

        if start_from > 0:
            empty_skus = empty_skus[start_from:]
            print(f"  → {start_from}번째부터 재개 (남은 상품: {len(empty_skus):,})")

        if not empty_skus:
            print("보완할 상품이 없습니다.")
            return

        # 브라우저 시작
        await self.setup_browser()

        try:
            collected_count = 0
            failed_count = 0
            total = len(empty_skus)

            for i, sku in enumerate(empty_skus):
                # URL 가져오기
                url = df.loc[df['Product_SKU'] == sku, 'URL'].iloc[0]

                print(f"[{i+1+start_from}/{total+start_from}] SKU: {sku}")

                # Description 수집
                description = await self.collect_description(url)

                if description:
                    # DataFrame 업데이트 (해당 SKU의 모든 행)
                    df.loc[df['Product_SKU'] == sku, 'Description'] = description
                    collected_count += 1
                    print(f"  ✓ {len(description)}자 수집")
                else:
                    failed_count += 1
                    print(f"  ✗ 수집 실패 (텍스트 없음)")

                # 배치 단위로 저장
                if (i + 1) % batch_size == 0:
                    print(f"\n=== 중간 저장 ({i+1}개 처리) ===")
                    df.to_excel(self.output_file, index=False)
                    print(f"저장 완료: {self.output_file}")
                    print(f"진행률: {(i+1)/total*100:.1f}% | 성공: {collected_count} | 실패: {failed_count}\n")

                # 딜레이
                await asyncio.sleep(0.5)

            # 최종 저장
            print(f"\n=== 최종 저장 ===")
            df.to_excel(self.output_file, index=False)
            print(f"저장 완료: {self.output_file}")

            print(f"\n=== 결과 ===")
            print(f"처리된 상품: {total:,}")
            print(f"성공: {collected_count:,}")
            print(f"실패: {failed_count:,}")

        finally:
            await self.close_browser()


async def main():
    input_file = "/Users/jihwanseok/Desktop/musinsa/musinsa_products_20260207_180752+(2).xlsx"

    filler = DescriptionFiller(input_file)
    await filler.run(batch_size=100, start_from=0)


if __name__ == "__main__":
    asyncio.run(main())
