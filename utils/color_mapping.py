"""
색상 매핑 유틸리티 (한글 → 영문)
"""
import json
import re
from pathlib import Path
from typing import Optional


# 기본 색상 매핑 테이블
DEFAULT_COLOR_MAP = {
    # 기본 색상
    "블랙": "Black",
    "검정": "Black",
    "검정색": "Black",
    "흑색": "Black",
    "화이트": "White",
    "흰색": "White",
    "백색": "White",
    "아이보리": "Ivory",
    "크림": "Cream",
    "베이지": "Beige",

    # 레드 계열
    "레드": "Red",
    "빨강": "Red",
    "빨간색": "Red",
    "적색": "Red",
    "와인": "Wine",
    "버건디": "Burgundy",
    "마룬": "Maroon",
    "코랄": "Coral",

    # 블루 계열
    "블루": "Blue",
    "파랑": "Blue",
    "파란색": "Blue",
    "청색": "Blue",
    "네이비": "Navy",
    "남색": "Navy",
    "스카이블루": "Sky Blue",
    "하늘색": "Sky Blue",
    "인디고": "Indigo",
    "민트": "Mint",
    "청록": "Teal",
    "터콰이즈": "Turquoise",

    # 그린 계열
    "그린": "Green",
    "초록": "Green",
    "녹색": "Green",
    "카키": "Khaki",
    "올리브": "Olive",
    "라임": "Lime",

    # 옐로우 계열
    "옐로우": "Yellow",
    "노랑": "Yellow",
    "노란색": "Yellow",
    "황색": "Yellow",
    "골드": "Gold",
    "금색": "Gold",
    "머스타드": "Mustard",

    # 오렌지 계열
    "오렌지": "Orange",
    "주황": "Orange",
    "주황색": "Orange",

    # 퍼플/핑크 계열
    "퍼플": "Purple",
    "보라": "Purple",
    "보라색": "Purple",
    "바이올렛": "Violet",
    "라벤더": "Lavender",
    "핑크": "Pink",
    "분홍": "Pink",
    "분홍색": "Pink",
    "로즈": "Rose",
    "마젠타": "Magenta",

    # 브라운 계열
    "브라운": "Brown",
    "갈색": "Brown",
    "탄": "Tan",
    "카멜": "Camel",
    "초콜릿": "Chocolate",
    "모카": "Mocha",
    "커피": "Coffee",

    # 그레이 계열
    "그레이": "Gray",
    "그래이": "Gray",
    "회색": "Gray",
    "차콜": "Charcoal",
    "실버": "Silver",
    "은색": "Silver",

    # 특수 색상
    "멀티": "Multi",
    "멀티컬러": "Multi",
    "믹스": "Mixed",
    "패턴": "Pattern",
    "투명": "Clear",
    "클리어": "Clear",

    # 영문 그대로 (이미 영문인 경우)
    "black": "Black",
    "white": "White",
    "red": "Red",
    "blue": "Blue",
    "green": "Green",
    "yellow": "Yellow",
    "pink": "Pink",
    "gray": "Gray",
    "grey": "Gray",
    "navy": "Navy",
    "brown": "Brown",
    "beige": "Beige",
    "orange": "Orange",
    "purple": "Purple",
}


class ColorMapper:
    """색상 매핑 클래스"""

    def __init__(self, custom_map_file: Optional[Path] = None):
        """
        초기화

        Args:
            custom_map_file: 사용자 정의 색상 매핑 파일 경로
        """
        self.color_map = DEFAULT_COLOR_MAP.copy()

        # 사용자 정의 매핑 파일 로드
        if custom_map_file and custom_map_file.exists():
            self._load_custom_map(custom_map_file)

    def _load_custom_map(self, file_path: Path):
        """사용자 정의 매핑 파일 로드"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                custom_map = json.load(f)
                self.color_map.update(custom_map)
        except Exception as e:
            print(f"색상 매핑 파일 로드 실패: {e}")

    def to_english(self, korean_color: str) -> str:
        """
        한글 색상을 영문으로 변환

        Args:
            korean_color: 한글 색상명

        Returns:
            영문 색상명 (변환 실패 시 원본 반환)
        """
        if not korean_color:
            return ""

        # 정확히 일치하는 경우
        color_lower = korean_color.lower().strip()
        if color_lower in self.color_map:
            return self.color_map[color_lower]

        # 부분 일치 검색
        for kor, eng in self.color_map.items():
            if kor in color_lower or color_lower in kor:
                return eng

        # 이미 영문인 경우 첫 글자 대문자로
        if re.match(r'^[a-zA-Z\s]+$', korean_color):
            return korean_color.title()

        # 변환 실패 시 원본 반환
        return korean_color

    def save_custom_map(self, file_path: Path):
        """현재 매핑 테이블을 파일로 저장"""
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.color_map, f, ensure_ascii=False, indent=2)

    def add_mapping(self, korean: str, english: str):
        """매핑 추가"""
        self.color_map[korean.lower()] = english


def create_default_color_map_file(file_path: Path):
    """기본 색상 매핑 파일 생성"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(DEFAULT_COLOR_MAP, f, ensure_ascii=False, indent=2)
    print(f"색상 매핑 파일 생성: {file_path}")
