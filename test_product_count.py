#!/usr/bin/env python3
"""최종 상품 수 확인 테스트"""
import asyncio
import re
from playwright.async_api import async_playwright

async def test_musinsa():
    url = "https://www.musinsa.com/category/103?gf=A&separatorId=9&brand=mizuno"
    print(f"무신사: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        count_text = await page.evaluate("""
            () => {
                const filterArea = document.querySelector('[class*="FilterSorting"]');
                if (filterArea) {
                    const span = filterArea.querySelector('span[data-mds="Typography"]');
                    if (span) return span.textContent.trim();
                }
                const allSpans = document.querySelectorAll('span');
                for (const span of allSpans) {
                    const text = span.textContent.trim();
                    if (/^\\d+(?:,\\d+)?개$/.test(text)) return text;
                }
                return null;
            }
        """)
        await browser.close()

        if count_text:
            match = re.search(r'(\d+(?:,\d+)?)', count_text)
            if match:
                total = int(match.group(1).replace(',', ''))
                pages = (total + 59) // 60
                print(f"  ✓ 전체 상품: {total:,}개 / {pages}페이지")
        else:
            print("  ✗ 상품 수를 찾을 수 없음")

async def test_naver():
    url = "https://brand.naver.com/adidas/category/033107a31e1b43b7ac24f2b17688f514?cp=1"
    print(f"\n네이버: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            viewport={'width': 1920, 'height': 1080}
        )
        page = await context.new_page()
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # 추가 대기 (JavaScript 렌더링)
        await asyncio.sleep(3)

        # 페이지 타이틀 확인
        title = await page.title()
        print(f"  페이지 타이틀: {title}")

        # 상품 개수 표시 영역 찾기 (클래스명 일부로)
        count_text = await page.evaluate("""
            () => {
                // 방법 1: "(총 XX개)" 패턴이 있는 span 찾기
                const allText = document.body.innerText;
                const match = allText.match(/\\(총\\s*(\\d+(?:,\\d+)?)\\s*개\\)/);
                if (match) return match[1];

                // 방법 2: strong 태그 안의 숫자 (부모에 "개"가 있는 경우)
                const strongs = document.querySelectorAll('strong');
                for (const strong of strongs) {
                    const num = strong.textContent.trim();
                    const parent = strong.parentElement;
                    if (parent && parent.textContent.includes('개') && /^\\d+$/.test(num)) {
                        return num;
                    }
                }

                return null;
            }
        """)
        print(f"  추출된 값: {count_text}")

        count_text = await page.evaluate("""
            () => {
                // "(총 XX개)" 패턴 찾기
                const spans = document.querySelectorAll('span');
                for (const span of spans) {
                    const text = span.textContent.trim();
                    if (text.includes('총') && text.includes('개')) {
                        const match = text.match(/총\\s*(\\d+(?:,\\d+)?)\\s*개/);
                        if (match) return match[1];
                    }
                }
                // strong 태그에서 찾기
                const strongs = document.querySelectorAll('strong');
                for (const strong of strongs) {
                    const parent = strong.parentElement;
                    if (parent && parent.textContent.includes('개')) {
                        const num = strong.textContent.trim();
                        if (/^\\d+(?:,\\d+)?$/.test(num)) return num;
                    }
                }
                return null;
            }
        """)
        await browser.close()

        if count_text:
            total = int(count_text.replace(',', ''))
            pages = (total + 79) // 80
            print(f"  ✓ 전체 상품: {total:,}개 / {pages}페이지")
        else:
            print("  ✗ 상품 수를 찾을 수 없음")

async def main():
    await test_musinsa()
    await test_naver()
    print("\n테스트 완료!")

if __name__ == "__main__":
    asyncio.run(main())
