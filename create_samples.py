"""
샘플 엑셀 파일 생성 (리뷰/평점/추가이미지 포함)
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from collectors.musinsa import MusinsaCollector
from collectors.naver import NaverSmartStoreCollector
from exporters.excel import export_to_excel


async def collect_musinsa_sample():
    """무신사 샘플 수집"""
    url = "https://www.musinsa.com/categories/item/003002"  # 운동화
    collector = MusinsaCollector(headless=False)

    try:
        await collector.setup_browser()
        print("=" * 50)
        print("무신사 샘플 수집")
        print("=" * 50)

        products = await collector.collect_category(url, start_page=1, end_page=1)
        print(f"카테고리: {len(products)}개 상품")

        # 상세 정보 수집 (10개)
        print("\n상세 정보 수집 중...")
        for i, product in enumerate(products[:10]):
            print(f"  [{i+1}/10] {product.product_name[:30]}...")
            await collector.collect_product_detail(product)
            options = await collector.collect_options(product)
            product.options = options  # 옵션 할당
            await asyncio.sleep(0.5)

        # 딕셔너리 변환
        products_data = []
        for p in products[:10]:
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

        # 엑셀 저장
        output_path = Path("/Users/jihwanseok/Desktop/musinsa/musinsa_sample_v2.xlsx")
        export_to_excel(products_data, "musinsa", output_path)
        print(f"\n저장 완료: {output_path}")

        return products_data

    finally:
        await collector.close_browser()


async def collect_naver_sample():
    """네이버 샘플 수집"""
    url = "https://brand.naver.com/adidas/category/033107a31e1b43b7ac24f2b17688f514"
    collector = NaverSmartStoreCollector(headless=False)

    try:
        await collector.setup_browser()
        print("\n" + "=" * 50)
        print("네이버 스마트스토어 샘플 수집")
        print("=" * 50)

        products = await collector.collect_category(url, start_page=1, end_page=1)
        print(f"카테고리: {len(products)}개 상품")

        # 상세 정보 수집 (10개)
        print("\n상세 정보 수집 중...")
        for i, product in enumerate(products[:10]):
            print(f"  [{i+1}/10] {product.product_name[:30]}...")
            await collector.collect_product_detail(product)
            options = await collector.collect_options(product)
            product.options = options  # 옵션 할당
            await asyncio.sleep(0.5)

        # 딕셔너리 변환
        products_data = []
        for p in products[:10]:
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

        # 엑셀 저장
        output_path = Path("/Users/jihwanseok/Desktop/musinsa/adidas_sample_v4.xlsx")
        export_to_excel(products_data, "naver", output_path)
        print(f"\n저장 완료: {output_path}")

        return products_data

    finally:
        await collector.close_browser()


async def main():
    # 무신사 샘플
    await collect_musinsa_sample()

    # 네이버 샘플
    await collect_naver_sample()

    print("\n" + "=" * 50)
    print("샘플 파일 생성 완료!")
    print("  - musinsa_sample_v2.xlsx")
    print("  - adidas_sample_v4.xlsx")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
