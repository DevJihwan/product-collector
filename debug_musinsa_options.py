"""
무신사 옵션 API 디버깅
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from playwright.async_api import async_playwright


async def main():
    # 테스트할 상품 ID (품절 옵션이 있을 가능성이 높은 인기 상품)
    goods_no = "3790498"  # 나이키 에어포스
    detail_url = f"https://www.musinsa.com/products/{goods_no}"
    options_url = f"https://goods-detail.musinsa.com/api2/goods/{goods_no}/options"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        # 상품 페이지 방문 (쿠키 획득)
        print(f"상품 페이지 방문: {detail_url}")
        await page.goto(detail_url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # 옵션 API 호출
        print(f"\n옵션 API 호출: {options_url}")
        response = await page.request.get(options_url, headers={
            'Accept': 'application/json',
            'Origin': 'https://www.musinsa.com',
            'Referer': detail_url
        })

        print(f"응답 상태: {response.status}")

        if response.status == 200:
            data = await response.json()
            print("\n=== API 응답 구조 ===")
            print(f"최상위 키: {list(data.keys())}")

            api_data = data.get('data', {})
            print(f"\ndata 키: {list(api_data.keys())}")

            # basic 구조
            basic_list = api_data.get('basic', [])
            print(f"\nbasic 개수: {len(basic_list)}")
            for i, basic in enumerate(basic_list):
                print(f"\n[basic {i}]")
                print(f"  name: {basic.get('name')}")
                print(f"  키: {list(basic.keys())}")
                opt_values = basic.get('optionValues', [])
                print(f"  optionValues 개수: {len(opt_values)}")
                if opt_values:
                    print(f"  첫번째 optionValue 키: {list(opt_values[0].keys())}")
                    for j, ov in enumerate(opt_values[:3]):
                        print(f"    [{j}] name={ov.get('name')}, id={ov.get('id')}, isDeleted={ov.get('isDeleted')}")

            # combination 구조
            combination_list = api_data.get('combination', [])
            print(f"\ncombination 개수: {len(combination_list)}")
            if combination_list:
                print(f"첫번째 combination 키: {list(combination_list[0].keys())}")
                for j, combo in enumerate(combination_list[:3]):
                    print(f"  [{j}] {combo}")

            # 전체 JSON 저장
            with open('output/debug_options_api.json', 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("\n전체 응답 저장: output/debug_options_api.json")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
