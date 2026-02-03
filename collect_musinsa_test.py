"""
무신사 수집 테스트 (리뷰/평점 포함)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collectors.musinsa import MusinsaCollector
from exporters.excel import export_to_excel
from config import OUTPUT_DIR


async def main():
    # 무신사 운동화 카테고리
    url = "https://www.musinsa.com/categories/item/003002"

    collector = MusinsaCollector(headless=False)

    try:
        await collector.setup_browser()

        print("=" * 50)
        print("무신사 수집 시작")
        print(f"URL: {url}")
        print("=" * 50)

        # 1페이지만 수집 (테스트)
        products = await collector.collect_category(url, start_page=1, end_page=1)
        print(f"\n카테고리에서 {len(products)}개 상품 수집 완료")

        # 상세 정보 수집 (처음 5개만 테스트)
        print("\n상세 정보 수집 중...")
        for i, product in enumerate(products[:5]):
            print(f"  [{i+1}/5] {product.product_name[:30]}...")
            await collector.collect_product_detail(product)
            product.options = await collector.collect_options(product)
            await asyncio.sleep(1)

        # 딕셔너리로 변환
        products_data = []
        for p in products[:5]:
            data = {
                'product_id': p.product_id,
                'product_name': p.product_name,
                'brand': p.brand,
                'price': p.price,
                'sale_price': p.sale_price,
                'image_url': p.image_url,
                'url': p.url,
                'options': [
                    {
                        'color': opt.color,
                        'size': opt.size,
                        'additional_price': opt.additional_price,
                        'stock': opt.stock,
                        'sold_out': opt.sold_out,
                    }
                    for opt in p.options
                ],
                'extra_info': p.extra_info,
            }
            products_data.append(data)

        # 리뷰/평점 확인
        print("\n" + "=" * 50)
        print("리뷰/평점 데이터 확인:")
        print("=" * 50)
        for p in products_data:
            review_count = p['extra_info'].get('review_count', 'N/A')
            rating = p['extra_info'].get('rating', 'N/A')
            print(f"  {p['product_name'][:25]:25} | 리뷰: {str(review_count):>5} | 평점: {rating}")

        # 옵션/품절 확인
        print("\n" + "=" * 50)
        print("옵션/품절 데이터 확인:")
        print("=" * 50)
        for p in products_data:
            print(f"\n▶ {p['product_name'][:40]}")
            options = p.get('options', [])
            if options:
                sold_out_count = sum(1 for opt in options if opt.get('sold_out'))
                print(f"  총 {len(options)}개 옵션 (품절: {sold_out_count}개)")
                for opt in options[:10]:  # 최대 10개만 표시
                    status = "❌품절" if opt.get('sold_out') else f"재고:{opt.get('stock', 0)}"
                    print(f"    - {opt.get('color', '-'):10} | {opt.get('size', '-'):8} | {status}")
                if len(options) > 10:
                    print(f"    ... 외 {len(options) - 10}개")
            else:
                print("  옵션 없음")

        # 엑셀 저장
        output_path = OUTPUT_DIR / "musinsa_with_reviews.xlsx"
        export_to_excel(products_data, "musinsa", output_path)
        print(f"\n엑셀 저장 완료: {output_path}")

    finally:
        await collector.close_browser()


if __name__ == "__main__":
    asyncio.run(main())
