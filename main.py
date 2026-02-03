#!/usr/bin/env python3
"""
무신사/네이버 스마트스토어 상품 데이터 수집 프로그램

사용법:
    python main.py <URL> [옵션]

예시:
    python main.py https://www.musinsa.com/categories/item/001
    python main.py https://brand.naver.com/koreaboardgames/category/xxx --start 1 --end 3
    python main.py https://www.musinsa.com/categories/item/001 --resume
"""

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

# 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, LOGS_DIR, CollectorConfig
from collectors.musinsa import MusinsaCollector, is_musinsa_url
from collectors.naver import NaverSmartStoreCollector, is_naver_store_url
from exporters.excel import JoomExcelExporter
from utils.logger import setup_logger


def print_banner():
    """배너 출력"""
    banner = """
╔══════════════════════════════════════════════════════════════════╗
║     무신사 / 네이버 스마트스토어 상품 데이터 수집 프로그램     ║
║                      v1.0 - Joom 형식 출력                       ║
╚══════════════════════════════════════════════════════════════════╝
"""
    print(banner)


def detect_site_type(url: str) -> str:
    """URL에서 사이트 유형 감지"""
    if is_musinsa_url(url):
        return "musinsa"
    elif is_naver_store_url(url):
        return "naver"
    else:
        raise ValueError(f"지원하지 않는 URL입니다: {url}")


def get_collector(site_type: str, headless: bool = True):
    """사이트 유형에 맞는 수집기 반환"""
    if site_type == "musinsa":
        return MusinsaCollector(headless=headless)
    elif site_type == "naver":
        return NaverSmartStoreCollector(headless=headless)
    else:
        raise ValueError(f"지원하지 않는 사이트 유형: {site_type}")


async def main_async(args):
    """비동기 메인 함수"""
    logger = setup_logger("main", LOGS_DIR)

    # 사이트 유형 감지
    try:
        site_type = detect_site_type(args.url)
        logger.info(f"사이트 유형: {site_type}")
    except ValueError as e:
        logger.error(str(e))
        return 1

    # 수집기 생성
    headless = not args.show_browser
    collector = get_collector(site_type, headless=headless)

    try:
        # 수집 실행
        logger.info("=" * 60)
        logger.info("상품 데이터 수집 시작")
        logger.info(f"  URL: {args.url}")
        logger.info(f"  페이지: {args.start} ~ {args.end if args.end else '전체'}")
        logger.info(f"  재개 모드: {'예' if args.resume else '아니오'}")
        logger.info("=" * 60)

        products = await collector.collect_all(
            url=args.url,
            start_page=args.start,
            end_page=args.end,
            resume=args.resume
        )

        if not products:
            logger.warning("수집된 상품이 없습니다.")
            return 1

        # 엑셀 출력
        logger.info("=" * 60)
        logger.info("엑셀 파일 생성")
        logger.info("=" * 60)

        # 상품 데이터를 딕셔너리 리스트로 변환
        products_data = collector.state.collected_products

        exporter = JoomExcelExporter(site_type)
        output_path = args.output
        if not output_path:
            output_path = None  # 자동 생성
        else:
            output_path = Path(output_path)

        excel_path = exporter.export(products_data, output_path)

        # 결과 요약
        logger.info("=" * 60)
        logger.info("수집 완료!")
        logger.info(f"  총 상품: {len(products)}개")
        logger.info(f"  성공: {len(collector.state.collected_products)}개")
        logger.info(f"  실패: {len(collector.state.failed_products)}개")
        logger.info(f"  엑셀 파일: {excel_path}")
        logger.info("=" * 60)

        # 실패 항목 출력
        if collector.state.failed_products:
            logger.warning("실패한 상품:")
            for item in collector.state.failed_products[:10]:
                logger.warning(f"  - {item.get('product_id')}: {item.get('error')}")
            if len(collector.state.failed_products) > 10:
                logger.warning(f"  ... 외 {len(collector.state.failed_products) - 10}개")

        return 0

    except KeyboardInterrupt:
        logger.warning("사용자에 의해 중단됨")
        logger.info("현재까지 수집된 데이터가 저장되었습니다.")
        return 130

    except Exception as e:
        logger.error(f"오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return 1


def main():
    """메인 함수"""
    print_banner()

    # 인자 파서 설정
    parser = argparse.ArgumentParser(
        description="무신사/네이버 스마트스토어 상품 데이터 수집 프로그램",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  무신사 카테고리 수집:
    python main.py https://www.musinsa.com/categories/item/001

  네이버 스마트스토어 수집:
    python main.py https://brand.naver.com/koreaboardgames/category/xxx

  페이지 범위 지정:
    python main.py <URL> --start 1 --end 5

  이전 수집 재개:
    python main.py <URL> --resume

  브라우저 표시:
    python main.py <URL> --show-browser
"""
    )

    parser.add_argument(
        "url",
        help="수집할 카테고리 페이지 URL (무신사 또는 네이버 스마트스토어)"
    )

    parser.add_argument(
        "--start", "-s",
        type=int,
        default=1,
        help="시작 페이지 (기본값: 1)"
    )

    parser.add_argument(
        "--end", "-e",
        type=int,
        default=None,
        help="종료 페이지 (지정하지 않으면 전체 페이지)"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="출력 파일 경로 (지정하지 않으면 자동 생성)"
    )

    parser.add_argument(
        "--resume", "-r",
        action="store_true",
        help="이전 수집 상태에서 재개"
    )

    parser.add_argument(
        "--show-browser",
        action="store_true",
        help="브라우저 창 표시 (디버깅용)"
    )

    args = parser.parse_args()

    # URL 검증
    parsed = urlparse(args.url)
    if not parsed.scheme or not parsed.netloc:
        print(f"오류: 유효하지 않은 URL입니다: {args.url}")
        return 1

    # 비동기 실행
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
