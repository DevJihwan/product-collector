#!/usr/bin/env python3
"""
무신사/네이버 스마트스토어 상품 데이터 수집 프로그램 - GUI 버전
"""

# ⚠️ 중요: 다른 모듈 import 전에 환경 변수 설정 (PyInstaller 호환)
import os
import sys
if getattr(sys, 'frozen', False):
    # PyInstaller exe 실행 시 시스템에 설치된 Playwright 브라우저 사용
    # Windows: %LOCALAPPDATA%\ms-playwright
    if sys.platform == 'win32':
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        if local_app_data:
            playwright_path = os.path.join(local_app_data, 'ms-playwright')
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = playwright_path
        else:
            os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'
    else:
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = '0'

import asyncio
import threading
import queue
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

# 모듈 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from config import OUTPUT_DIR, LOGS_DIR
from collectors.musinsa import MusinsaCollector, is_musinsa_url
from collectors.naver import NaverSmartStoreCollector, is_naver_store_url
from collectors.daiso import DaisoCollector, is_daiso_url
from exporters.excel import JoomExcelExporter

# 테마 설정
ctk.set_appearance_mode("Light")  # Light 모드
ctk.set_default_color_theme("blue")


class LogHandler:
    """로그 메시지를 큐로 전달하는 핸들러"""
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, message):
        if message.strip():
            self.log_queue.put(message)

    def flush(self):
        pass


class CollectorApp(ctk.CTk):
    """상품 데이터 수집 프로그램 GUI"""

    def __init__(self):
        super().__init__()

        # 윈도우 설정
        self.title("상품 데이터 수집 프로그램 v1.0")
        self.geometry("900x700")
        self.minsize(800, 600)

        # 상태 변수
        self.is_collecting = False
        self.collector = None
        self.log_queue = queue.Queue()

        # UI 구성
        self._create_widgets()

        # 로그 업데이트 시작
        self._update_log()

    def _create_widgets(self):
        """UI 위젯 생성"""
        # 메인 프레임
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(fill="both", expand=True, padx=20, pady=20)

        # === 상단: 입력 영역 ===
        self._create_input_section()

        # === 중단: 옵션 영역 ===
        self._create_options_section()

        # === 버튼 영역 ===
        self._create_buttons_section()

        # === 진행률 영역 ===
        self._create_progress_section()

        # === 로그 영역 ===
        self._create_log_section()

    def _create_input_section(self):
        """입력 영역 생성"""
        input_frame = ctk.CTkFrame(self.main_frame)
        input_frame.pack(fill="x", pady=(0, 15))

        # 제목
        title_label = ctk.CTkLabel(
            input_frame,
            text="무신사 / 네이버 스마트스토어 상품 데이터 수집",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack(pady=15)

        # URL 입력
        url_frame = ctk.CTkFrame(input_frame, fg_color="transparent")
        url_frame.pack(fill="x", padx=20, pady=5)

        url_label = ctk.CTkLabel(url_frame, text="카테고리 URL:", width=100, anchor="w")
        url_label.pack(side="left")

        self.url_entry = ctk.CTkEntry(url_frame, placeholder_text="https://www.musinsa.com/categories/item/001")
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(10, 0))

        # Cmd+V / Ctrl+V 바인딩 (macOS와 Windows 모두 지원)
        self.url_entry.bind("<Command-v>", self._paste_to_entry)
        self.url_entry.bind("<Control-v>", self._paste_to_entry)
        # 내부 Entry 위젯에도 바인딩 (CustomTkinter 호환성)
        if hasattr(self.url_entry, '_entry'):
            self.url_entry._entry.bind("<Command-v>", self._paste_to_entry)
            self.url_entry._entry.bind("<Control-v>", self._paste_to_entry)

        # 붙여넣기 버튼 추가
        paste_btn = ctk.CTkButton(url_frame, text="붙여넣기", width=70, command=self._paste_url)
        paste_btn.pack(side="left", padx=(5, 0))

        # 확인 버튼 추가
        self.check_btn = ctk.CTkButton(url_frame, text="확인", width=60, fg_color="gray", command=self._check_total_count)
        self.check_btn.pack(side="left", padx=(5, 0))

        # 사이트 유형 표시
        self.site_label = ctk.CTkLabel(url_frame, text="", width=80)
        self.site_label.pack(side="right", padx=(10, 0))

        # URL 경고/정보 레이블
        self.url_warning_label = ctk.CTkLabel(
            input_frame,
            text="",
            text_color="orange",
            font=ctk.CTkFont(size=12)
        )
        self.url_warning_label.pack(fill="x", padx=120, pady=(0, 2))

        # 상품 수 정보 레이블
        self.product_count_label = ctk.CTkLabel(
            input_frame,
            text="",
            text_color="green",
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.product_count_label.pack(fill="x", padx=120, pady=(0, 5))

        # URL 변경 감지
        self.url_entry.bind("<KeyRelease>", self._on_url_change)

    def _create_options_section(self):
        """옵션 영역 생성"""
        options_frame = ctk.CTkFrame(self.main_frame)
        options_frame.pack(fill="x", pady=(0, 15))

        # 수집 범위 설정
        count_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        count_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(count_frame, text="수집 범위:", width=100, anchor="w").pack(side="left")

        # 전체 수집 체크박스
        self.all_products_var = ctk.BooleanVar(value=True)
        self.all_products_check = ctk.CTkCheckBox(
            count_frame,
            text="전체 수집",
            variable=self.all_products_var,
            command=self._on_all_products_toggle
        )
        self.all_products_check.pack(side="left", padx=(10, 20))

        # 범위 입력 (시작 ~ 끝)
        ctk.CTkLabel(count_frame, text="또는").pack(side="left", padx=(0, 10))

        self.range_start_entry = ctk.CTkEntry(count_frame, width=70, placeholder_text="시작")
        self.range_start_entry.pack(side="left")
        self.range_start_entry.configure(state="disabled")

        ctk.CTkLabel(count_frame, text="~").pack(side="left", padx=(5, 5))

        self.range_end_entry = ctk.CTkEntry(count_frame, width=70, placeholder_text="끝")
        self.range_end_entry.pack(side="left")
        self.range_end_entry.configure(state="disabled")

        ctk.CTkLabel(count_frame, text="번 상품 (예: 1~100, 201~300)").pack(side="left", padx=(10, 0))

        # 출력 파일
        output_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        output_frame.pack(fill="x", padx=20, pady=10)

        ctk.CTkLabel(output_frame, text="저장 위치:", width=100, anchor="w").pack(side="left")

        self.output_entry = ctk.CTkEntry(output_frame, placeholder_text="자동 생성")
        self.output_entry.pack(side="left", fill="x", expand=True, padx=(10, 10))

        browse_btn = ctk.CTkButton(output_frame, text="찾아보기", width=80, command=self._browse_output)
        browse_btn.pack(side="right")

        # 브라우저 표시 옵션
        browser_frame = ctk.CTkFrame(options_frame, fg_color="transparent")
        browser_frame.pack(fill="x", padx=20, pady=10)

        self.show_browser_var = ctk.BooleanVar(value=False)
        self.show_browser_check = ctk.CTkCheckBox(
            browser_frame,
            text="브라우저 창 표시 (디버깅용)",
            variable=self.show_browser_var
        )
        self.show_browser_check.pack(side="left")

    def _create_buttons_section(self):
        """버튼 영역 생성"""
        btn_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", pady=5)

        self.start_btn = ctk.CTkButton(
            btn_frame,
            text="수집 시작",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=32,
            width=120,
            command=self._start_collection
        )
        self.start_btn.pack(side="left", padx=(20, 10))

        self.stop_btn = ctk.CTkButton(
            btn_frame,
            text="중지",
            font=ctk.CTkFont(size=13),
            height=32,
            width=80,
            fg_color="gray",
            state="disabled",
            command=self._stop_collection
        )
        self.stop_btn.pack(side="left", padx=(0, 20))

    def _create_progress_section(self):
        """진행률 영역 생성"""
        progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        progress_frame.pack(fill="x", pady=(0, 5))

        # 상태 + 진행률을 한 줄에 표시
        status_row = ctk.CTkFrame(progress_frame, fg_color="transparent")
        status_row.pack(fill="x", padx=20)

        # 상태 레이블
        self.status_label = ctk.CTkLabel(
            status_row,
            text="대기 중...",
            font=ctk.CTkFont(size=12),
            anchor="w"
        )
        self.status_label.pack(side="left")

        # 진행률 텍스트
        self.progress_label = ctk.CTkLabel(status_row, text="0%", font=ctk.CTkFont(size=12))
        self.progress_label.pack(side="right")

        # 진행률 바
        self.progress_bar = ctk.CTkProgressBar(progress_frame, height=8)
        self.progress_bar.pack(fill="x", padx=20, pady=(3, 5))
        self.progress_bar.set(0)

    def _create_log_section(self):
        """로그 영역 생성"""
        log_frame = ctk.CTkFrame(self.main_frame)
        log_frame.pack(fill="both", expand=True)

        log_label = ctk.CTkLabel(log_frame, text="로그", anchor="w")
        log_label.pack(fill="x", padx=10, pady=(10, 5))

        self.log_text = ctk.CTkTextbox(log_frame, font=ctk.CTkFont(family="Courier", size=12))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _paste_to_entry(self, event=None):
        """Entry 위젯에 Cmd+V/Ctrl+V로 붙여넣기"""
        try:
            # 클립보드 내용 가져오기
            clipboard = self.clipboard_get()
            if clipboard:
                # 선택된 텍스트가 있으면 삭제
                try:
                    self.url_entry.delete("sel.first", "sel.last")
                except:
                    pass
                # 현재 커서 위치에 삽입
                self.url_entry.insert("insert", clipboard.strip())
                # URL 변경 이벤트 트리거
                self._on_url_change()
        except Exception as e:
            self._log(f"붙여넣기 실패: {e}")
        return "break"

    def _paste_url(self, event=None):
        """클립보드에서 URL 붙여넣기 (버튼용 - 전체 교체)"""
        try:
            # 클립보드 내용 가져오기
            clipboard = self.clipboard_get()
            # 기존 내용 삭제 후 붙여넣기
            self.url_entry.delete(0, "end")
            self.url_entry.insert(0, clipboard.strip())
            # URL 변경 이벤트 트리거
            self._on_url_change()
        except Exception as e:
            self._log(f"붙여넣기 실패: {e}")
        return "break"

    def _on_url_change(self, event=None):
        """URL 변경 시 사이트 유형 감지 및 URL 유형 검증"""
        url = self.url_entry.get().strip()
        if not url:
            self.site_label.configure(text="")
            self.url_warning_label.configure(text="")
            return

        # URL 유형 검증
        warning_text = ""

        if is_musinsa_url(url):
            self.site_label.configure(text="[무신사]", text_color="green")
            # 무신사: 상품 페이지 URL만 경고
            if '/products/' in url:
                warning_text = "⚠️ 상품 페이지 URL입니다. 카테고리 URL을 입력해주세요."
        elif is_naver_store_url(url):
            self.site_label.configure(text="[네이버]", text_color="blue")
            # 네이버: 상품 페이지 URL만 경고
            if '/products/' in url:
                warning_text = "⚠️ 상품 페이지 URL입니다. 카테고리 URL을 입력해주세요."
        else:
            self.site_label.configure(text="[미지원]", text_color="red")
            warning_text = "⚠️ 무신사 또는 네이버 스마트스토어 URL만 지원합니다."

        self.url_warning_label.configure(text=warning_text)
        # 상품 수 정보 초기화
        self.product_count_label.configure(text="")

    def _check_total_count(self):
        """URL의 전체 상품 수 확인"""
        url = self.url_entry.get().strip()
        if not url:
            self.product_count_label.configure(text="URL을 입력해주세요.", text_color="orange")
            return

        # 상품 페이지 URL 체크
        if '/products/' in url:
            self.product_count_label.configure(text="카테고리 URL을 입력해주세요.", text_color="orange")
            return

        if not is_musinsa_url(url) and not is_naver_store_url(url) and not is_daiso_url(url):
            self.product_count_label.configure(text="지원하지 않는 URL입니다.", text_color="red")
            return

        # 버튼 비활성화 및 로딩 표시
        self.check_btn.configure(state="disabled", text="확인중...")
        self.product_count_label.configure(text="조회 중...", text_color="gray")

        # 별도 스레드에서 확인
        thread = threading.Thread(target=self._fetch_total_count, args=(url,), daemon=True)
        thread.start()

    def _fetch_total_count(self, url: str):
        """전체 상품 수 가져오기 (별도 스레드)"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._async_fetch_count(url))
            self.after(0, lambda: self._show_count_result(result))
        except Exception as e:
            self.after(0, lambda: self._show_count_result({'error': str(e)}))

    async def _async_fetch_count(self, url: str) -> dict:
        """비동기로 상품 수 조회"""
        import re
        from playwright.async_api import async_playwright

        try:
            if is_musinsa_url(url):
                # 무신사: 브라우저로 DOM에서 상품 수 추출
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    page = await browser.new_page()

                    try:
                        await page.goto(url, wait_until="networkidle", timeout=30000)

                        # DOM에서 "XXX개" 텍스트 추출
                        count_text = await page.evaluate("""
                            () => {
                                // FilterSorting 영역에서 상품 수 찾기
                                const filterArea = document.querySelector('[class*="FilterSorting"]');
                                if (filterArea) {
                                    const span = filterArea.querySelector('span[data-mds="Typography"]');
                                    if (span) return span.textContent.trim();
                                }
                                // 대안: 전체에서 "XXX개" 패턴 찾기
                                const allSpans = document.querySelectorAll('span');
                                for (const span of allSpans) {
                                    const text = span.textContent.trim();
                                    if (/^\\d+(?:,\\d+)?개$/.test(text)) {
                                        return text;
                                    }
                                }
                                return null;
                            }
                        """)

                        await browser.close()

                        if count_text:
                            # "139개" -> 139
                            count_match = re.search(r'(\d+(?:,\d+)?)', count_text)
                            if count_match:
                                total_count = int(count_match.group(1).replace(',', ''))
                                total_pages = (total_count + 59) // 60  # 60개씩 페이지
                                return {
                                    'total_count': total_count,
                                    'total_pages': total_pages,
                                    'site': '무신사'
                                }

                        return {'error': '상품 수를 찾을 수 없습니다.'}

                    except Exception as e:
                        await browser.close()
                        return {'error': str(e)}

            elif is_naver_store_url(url):
                # 네이버: 브라우저로 DOM에서 "(총 XX개)" 추출
                async with async_playwright() as p:
                    browser = await p.chromium.launch(headless=True)
                    # 네이버는 User-Agent와 viewport 설정 필요
                    context = await browser.new_context(
                        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        viewport={'width': 1920, 'height': 1080}
                    )
                    page = await context.new_page()

                    try:
                        await page.goto(url, wait_until="networkidle", timeout=30000)

                        # JavaScript 렌더링 대기
                        await asyncio.sleep(2)

                        # DOM에서 "(총 XX개)" 패턴 추출
                        count_text = await page.evaluate("""
                            () => {
                                // 방법 1: document.body.innerText에서 "(총 XX개)" 패턴 찾기
                                const allText = document.body.innerText;
                                const match = allText.match(/\\(총\\s*(\\d+(?:,\\d+)?)\\s*개\\)/);
                                if (match) return match[1];

                                // 방법 2: span 태그에서 "총 XX개" 패턴 찾기
                                const spans = document.querySelectorAll('span');
                                for (const span of spans) {
                                    const text = span.textContent.trim();
                                    if (text.includes('총') && text.includes('개')) {
                                        const spanMatch = text.match(/총\\s*(\\d+(?:,\\d+)?)\\s*개/);
                                        if (spanMatch) return spanMatch[1];
                                    }
                                }

                                // 방법 3: strong 태그에서 직접 찾기
                                const strongs = document.querySelectorAll('strong');
                                for (const strong of strongs) {
                                    const parent = strong.parentElement;
                                    if (parent && parent.textContent.includes('개')) {
                                        const num = strong.textContent.trim();
                                        if (/^\\d+(?:,\\d+)?$/.test(num)) {
                                            return num;
                                        }
                                    }
                                }
                                return null;
                            }
                        """)

                        await browser.close()

                        if count_text:
                            total_count = int(count_text.replace(',', ''))
                            total_pages = (total_count + 79) // 80  # 네이버는 80개씩 페이지
                            return {
                                'total_count': total_count,
                                'total_pages': total_pages,
                                'site': '네이버'
                            }

                        return {'error': '상품 수를 찾을 수 없습니다.'}

                    except Exception as e:
                        await browser.close()
                        return {'error': str(e)}

            elif is_daiso_url(url):
                # 다이소: API로 상품 수 조회
                import aiohttp
                from config import DaisoConfig

                # URL에서 카테고리 정보 추출
                parsed = urlparse(url)
                path_parts = parsed.path.strip('/').split('/')
                # /ds/exhCtgr/C208/{대분류}/{중분류}
                if len(path_parts) >= 5:
                    large_ctgr = path_parts[3]
                    ctgr_no = path_parts[4]
                else:
                    return {'error': '카테고리 URL 형식이 올바르지 않습니다.'}

                api_url = f"{DaisoConfig.SEARCH_API}?pageNum=1&cntPerPage=1&largeExhCtgrNo={large_ctgr}&exhCtgrNo={ctgr_no}"

                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(api_url) as response:
                            if response.status == 200:
                                data = await response.json()
                                result_set = data.get('resultSet', {})
                                result_list = result_set.get('result', [])
                                if len(result_list) >= 2:
                                    total_count = result_list[1].get('totalSize', 0)
                                    total_pages = (total_count + 29) // 30  # 30개씩 페이지
                                    return {
                                        'total_count': total_count,
                                        'total_pages': total_pages,
                                        'site': '다이소'
                                    }
                            return {'error': 'API 응답 오류'}
                except Exception as e:
                    return {'error': str(e)}

        except Exception as e:
            return {'error': str(e)}

        return {'error': '알 수 없는 오류'}

    def _show_count_result(self, result: dict):
        """상품 수 조회 결과 표시"""
        self.check_btn.configure(state="normal", text="확인")

        if 'error' in result:
            self.product_count_label.configure(
                text=f"❌ {result['error']}",
                text_color="red"
            )
        else:
            total = result['total_count']
            pages = result['total_pages']
            site = result['site']
            self.product_count_label.configure(
                text=f"📦 전체 상품: {total:,}개 / {pages:,}페이지",
                text_color="green"
            )

    def _on_all_products_toggle(self):
        """전체 수집 체크박스 토글"""
        if self.all_products_var.get():
            # 전체 수집 선택 시 - 범위 입력 비활성화
            self.range_start_entry.configure(state="normal")
            self.range_start_entry.delete(0, "end")
            self.range_start_entry.configure(state="disabled")
            self.range_end_entry.configure(state="normal")
            self.range_end_entry.delete(0, "end")
            self.range_end_entry.configure(state="disabled")
        else:
            # 범위 지정 선택 시 - 입력 필드 활성화
            self.range_start_entry.configure(state="normal")
            self.range_end_entry.configure(state="normal")
            self.range_start_entry.focus_set()  # 포커스 이동

    def _browse_output(self):
        """출력 파일 위치 선택"""
        file_path = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx"), ("All files", "*.*")],
            initialdir=OUTPUT_DIR
        )
        if file_path:
            self.output_entry.delete(0, "end")
            self.output_entry.insert(0, file_path)

    def _log(self, message):
        """로그 메시지 추가"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def _update_log(self):
        """로그 큐에서 메시지를 가져와 텍스트박스에 추가"""
        try:
            while True:
                message = self.log_queue.get_nowait()
                self.log_text.insert("end", message + "\n")
                self.log_text.see("end")
        except queue.Empty:
            pass

        # 100ms 후 다시 확인
        self.after(100, self._update_log)

    def _validate_inputs(self):
        """입력값 검증"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showerror("오류", "URL을 입력해주세요.")
            return False

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            messagebox.showerror("오류", "유효하지 않은 URL입니다.")
            return False

        if not is_musinsa_url(url) and not is_naver_store_url(url) and not is_daiso_url(url):
            messagebox.showerror("오류", "지원하지 않는 사이트입니다.\n무신사, 네이버 스마트스토어 또는 다이소몰 URL을 입력해주세요.")
            return False

        # 카테고리 URL 검증
        if is_musinsa_url(url):
            # 무신사: 상품 페이지 URL만 차단
            if '/products/' in url:
                messagebox.showerror("오류", "상품 페이지 URL입니다.\n카테고리 URL을 입력해주세요.")
                return False
        elif is_naver_store_url(url):
            # 네이버: 상품 페이지 URL만 차단
            if '/products/' in url:
                messagebox.showerror("오류", "상품 페이지 URL입니다.\n카테고리 URL을 입력해주세요.")
                return False
        elif is_daiso_url(url):
            # 다이소: 상품 페이지 URL 차단
            if 'pdNo=' in url or '/pdr/' in url:
                messagebox.showerror("오류", "상품 페이지 URL입니다.\n카테고리 URL을 입력해주세요.")
                return False

        return True

    def _start_collection(self):
        """수집 시작"""
        if not self._validate_inputs():
            return

        self.is_collecting = True
        self._set_ui_state(collecting=True)
        self._log("수집을 시작합니다...")

        # 별도 스레드에서 수집 실행
        thread = threading.Thread(target=self._run_collection, daemon=True)
        thread.start()

    def _stop_collection(self):
        """수집 중지"""
        self.is_collecting = False
        self._log("⏹️ 수집 중지 요청됨... 현재 작업 완료 후 중지됩니다.")
        self._update_status("중지 중...")

    def _set_ui_state(self, collecting: bool):
        """UI 상태 설정"""
        state = "disabled" if collecting else "normal"
        self.url_entry.configure(state=state)
        self.all_products_check.configure(state=state)
        self.output_entry.configure(state=state)
        self.show_browser_check.configure(state=state)

        if collecting:
            self.start_btn.configure(state="disabled")
            self.stop_btn.configure(state="normal", fg_color="red")
            self.range_start_entry.configure(state="disabled")
            self.range_end_entry.configure(state="disabled")
        else:
            self.start_btn.configure(state="normal")
            self.stop_btn.configure(state="disabled", fg_color="gray")
            if not self.all_products_var.get():
                self.range_start_entry.configure(state="normal")
                self.range_end_entry.configure(state="normal")

    def _run_collection(self):
        """수집 실행 (별도 스레드)"""
        was_stopped = False
        try:
            # 비동기 이벤트 루프 생성 및 실행
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._async_collection())
        except Exception as e:
            self._log(f"오류 발생: {e}")
        finally:
            was_stopped = not self.is_collecting
            self.is_collecting = False
            self.after(0, lambda: self._set_ui_state(collecting=False))
            status_text = "중지됨" if was_stopped else "완료"
            self.after(0, lambda: self.status_label.configure(text=status_text))

    async def _async_collection(self):
        """비동기 수집 로직"""
        url = self.url_entry.get().strip()
        # 수집 범위 (전체 수집이면 None, None)
        range_start = None
        range_end = None
        if not self.all_products_var.get():
            start_text = self.range_start_entry.get().strip()
            end_text = self.range_end_entry.get().strip()
            if start_text:
                range_start = int(start_text)
            if end_text:
                range_end = int(end_text)
        headless = not self.show_browser_var.get()

        # 사이트 유형 감지
        if is_musinsa_url(url):
            site_type = "musinsa"
            site_name = "무신사"
            self.collector = MusinsaCollector(headless=headless)
        elif is_naver_store_url(url):
            site_type = "naver"
            site_name = "네이버 스마트스토어"
            self.collector = NaverSmartStoreCollector(headless=headless)
        else:
            site_type = "daiso"
            site_name = "다이소몰"
            self.collector = DaisoCollector(headless=headless)

        # 로그 콜백 설정 (GUI 로그에 표시)
        self.collector.log_callback = self._log
        # 중지 체크 콜백 설정
        self.collector.stop_check = lambda: not self.is_collecting

        self._log("=" * 50)
        self._log("수집 시작")
        self._log("=" * 50)
        self._log(f"사이트: {site_name}")
        self._log(f"URL: {url}")
        if range_start is None and range_end is None:
            self._log(f"수집 범위: 전체")
        else:
            start_str = str(range_start) if range_start else "1"
            end_str = str(range_end) if range_end else "끝"
            self._log(f"수집 범위: {start_str} ~ {end_str}번 상품")
        self._log(f"브라우저 표시: {'예' if not headless else '아니오'}")
        self._log("-" * 50)

        try:
            self._log("브라우저 시작 중...")
            # 디버그: 브라우저 경로 표시
            browser_path = os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '(not set)')
            self._log(f"  브라우저 경로: {browser_path}")
            try:
                await self.collector.setup_browser()
            except Exception as browser_error:
                error_msg = str(browser_error)
                if "Executable doesn't exist" in error_msg or "playwright install" in error_msg:
                    self._log("=" * 50)
                    self._log("❌ 브라우저가 설치되지 않았습니다!")
                    self._log("")
                    self._log(f"현재 브라우저 검색 경로: {browser_path}")
                    self._log("")
                    self._log("해결 방법:")
                    self._log("  1. install_browser.bat 파일을 더블클릭하여 실행")
                    self._log("  또는")
                    self._log("  2. 명령 프롬프트(CMD)에서 아래 명령어 실행:")
                    self._log("     python -m playwright install chromium")
                    self._log("")
                    self._log("브라우저 설치 후 프로그램을 다시 실행해주세요.")
                    self._log("=" * 50)
                    return
                raise
            self._log("브라우저 시작 완료")
            self._log("-" * 50)

            # 1단계: 카테고리 수집
            self._log("[1단계] 카테고리 페이지에서 상품 목록 수집")
            self._update_status("카테고리 페이지 수집 중...")
            products = await self.collector.collect_category(url, start_page=1, end_page=None)

            total_pages = self.collector.state.total_pages
            total_found = len(products)
            self._log(f"총 페이지: {total_pages}페이지")
            self._log(f"상품 목록 수집 완료: {total_found}개 상품 발견")

            # 수집 범위 적용 (1-indexed를 0-indexed로 변환)
            if range_start is not None or range_end is not None:
                start_idx = (range_start - 1) if range_start else 0
                end_idx = range_end if range_end else len(products)
                # 유효 범위 검증
                start_idx = max(0, start_idx)
                end_idx = min(len(products), end_idx)
                if start_idx < end_idx:
                    products = products[start_idx:end_idx]
                    self._log(f"지정 범위 적용: {start_idx + 1}~{end_idx}번 상품 ({len(products)}개)")
                else:
                    self._log(f"⚠️ 잘못된 범위입니다. (시작: {range_start}, 끝: {range_end})")
                    return
            self._log("-" * 50)

            if not products:
                self._log("⚠️ 수집된 상품이 없습니다. URL을 확인해주세요.")
                return

            # 중지 요청 체크
            if not self.is_collecting:
                self._log("⚠️ 사용자에 의해 수집이 중지되었습니다.")
                return

            # 2단계: 상세 정보 + 옵션 수집
            self._log(f"[2단계] 상품 상세 정보 수집 (총 {len(products)}개)")
            total = len(products)

            for i, product in enumerate(products):
                if not self.is_collecting:
                    self._log("⚠️ 사용자에 의해 수집이 중지되었습니다.")
                    break

                progress = (i + 1) / total
                self._update_progress(progress, f"상세 수집 중: [{i+1}/{total}]")

                # 상품명 (길이 제한)
                product_name_short = product.product_name[:35] + "..." if len(product.product_name) > 35 else product.product_name
                self._log(f"  [{i+1}/{total}] {product_name_short}")

                try:
                    # 상세 정보 수집
                    product = await self.collector.collect_product_detail(product)

                    # 옵션 수집
                    product.options = await self.collector.collect_options(product)

                    # 수집 결과 로그
                    extra_info = product.extra_info
                    options_count = len(product.options)
                    review_count = extra_info.get('review_count', 0)
                    rating = extra_info.get('rating', 0)
                    extra_images_count = len(extra_info.get('extra_images', []))

                    self._log(f"       → 옵션: {options_count}개 | 리뷰: {review_count}개 | 평점: {rating} | 이미지: {extra_images_count + 1}장")

                    self.collector.state.collected_products.append(
                        self.collector._product_to_dict(product)
                    )

                    # 10개마다 자동 저장
                    collected_count = len(self.collector.state.collected_products)
                    if collected_count > 0 and collected_count % 10 == 0:
                        self._auto_save(site_type, collected_count, category_url=url)

                except Exception as e:
                    self._log(f"       → ❌ 수집 실패: {e}")
                    self.collector.state.failed_products.append({
                        "product_id": product.product_id,
                        "error": str(e)
                    })

                await self.collector.random_delay()

            # 수집 종료 시 남은 데이터 자동 저장 (10개 미만인 경우)
            collected_count = len(self.collector.state.collected_products)
            if collected_count > 0 and collected_count % 10 != 0:
                self._auto_save(site_type, collected_count, category_url=url)

            self._log("-" * 50)

            # 3단계: 엑셀 출력
            self._log("[3단계] 엑셀 파일 생성")
            self._update_status("엑셀 파일 생성 중...")
            products_data = self.collector.state.collected_products

            output_path = self.output_entry.get().strip()
            if output_path:
                output_path = Path(output_path)
            else:
                output_path = None

            exporter = JoomExcelExporter(site_type)
            excel_path = exporter.export(products_data, output_path, category_url=url)

            # 총 옵션 수 및 행 수 계산
            total_options = sum(len(p.get('options', [])) for p in products_data)
            total_rows = sum(max(1, len(p.get('options', []))) for p in products_data)

            # 결과 요약
            self._log("=" * 50)
            self._log("✅ 수집 완료!")
            self._log("=" * 50)
            self._log(f"  📦 수집 상품: {len(self.collector.state.collected_products)}개")
            self._log(f"  🎨 총 옵션: {total_options}개")
            self._log(f"  📊 엑셀 행: {total_rows}행 (옵션별 1행)")
            self._log(f"  ❌ 실패: {len(self.collector.state.failed_products)}개")
            self._log("-" * 50)
            self._log(f"  📁 저장 위치: {excel_path}")
            self._log("=" * 50)

            # 완료 메시지
            self.after(0, lambda: messagebox.showinfo(
                "완료",
                f"수집이 완료되었습니다!\n\n"
                f"수집 상품: {len(self.collector.state.collected_products)}개\n"
                f"총 옵션: {total_options}개\n"
                f"엑셀 행: {total_rows}행\n\n"
                f"저장 위치:\n{excel_path}"
            ))

        finally:
            await self.collector.close_browser()

    def _update_status(self, text):
        """상태 레이블 업데이트 (메인 스레드에서)"""
        self.after(0, lambda: self.status_label.configure(text=text))

    def _update_progress(self, value, text=""):
        """진행률 업데이트 (메인 스레드에서)"""
        self.after(0, lambda: self.progress_bar.set(value))
        self.after(0, lambda: self.progress_label.configure(text=f"{int(value * 100)}%"))
        if text:
            self.after(0, lambda: self.status_label.configure(text=text))

    def _auto_save(self, site_type: str, count: int, category_url: str = None):
        """중간 자동 저장 (10개 상품마다, 동일 파일 덮어쓰기)"""
        try:
            products_data = self.collector.state.collected_products
            if not products_data:
                return

            # 자동 저장 파일명: 동일 파일 덮어쓰기
            auto_save_path = OUTPUT_DIR / f"{site_type}_autosave_진행중.xlsx"

            exporter = JoomExcelExporter(site_type)
            exporter.export(products_data, auto_save_path, category_url=category_url)

            self._log(f"    💾 자동 저장: {count}개 상품 ({auto_save_path.name})")

        except Exception as e:
            self._log(f"    ⚠️ 자동 저장 실패: {e}")


def main():
    """메인 함수"""
    app = CollectorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
