# Windows 설치 및 실행 가이드

## 개발자용 (exe 빌드)

### 요구사항
- Windows 10/11
- Python 3.10 이상 (PATH 등록 필수)
- Chrome 브라우저

### 빌드 방법

1. **프로젝트 폴더를 단순 경로로 이동**
   ```
   권장: C:\collector
   피해야 할 경로: C:\Users\사용자\OneDrive\바탕 화면\...
   ```

2. **build_windows.bat 실행**
   - 더블클릭으로 실행
   - 또는 CMD에서: `build_windows.bat`

3. **빌드 완료 후**
   - `dist\ProductCollector.exe` 생성됨

### 빌드 문제 해결

| 문제 | 해결 방법 |
|-----|---------|
| Python not found | Python 재설치, PATH 체크 |
| venv 생성 실패 | 프로젝트를 C:\ 근처로 이동 |
| pip 인식 안됨 | `python -m pip` 사용 |
| Build failed | venv 삭제 후 재시도 |

---

## 사용자용 (exe 실행)

### 요구사항
- Windows 10/11
- Chrome 브라우저
- **Playwright 브라우저** (최초 1회 설치 필요)

### 최초 설치 (1회만)

exe 파일 실행 전에 Playwright 브라우저를 설치해야 합니다.

**방법 1: 설치 스크립트 사용**
1. `install_browser.bat` 더블클릭

**방법 2: 수동 설치**
1. CMD(명령 프롬프트) 열기
2. 다음 명령어 실행:
   ```
   pip install playwright
   playwright install chromium
   ```

### 프로그램 실행

1. `ProductCollector.exe` 더블클릭
2. 카테고리 URL 입력
3. 수집 범위 설정:
   - **전체 수집**: "전체 수집" 체크
   - **범위 지정**: 시작 ~ 끝 번호 입력 (예: 1~100, 201~300)
4. "수집 시작" 클릭

### 자동 저장 기능

- **10개 상품마다 자동 저장**
- 파일 위치: `output/{사이트}_autosave_진행중.xlsx` (단일 파일)
- 동일 파일에 최신 데이터 덮어쓰기
- 프로그램 오류로 종료되어도 자동 저장 파일에서 진행 상황 확인 가능

### 이어서 수집하기

프로그램이 중단된 경우:
1. 자동 저장 파일 확인 (예: `musinsa_autosave_진행중.xlsx`)
2. 엑셀 파일을 열어 몇 개가 저장되었는지 확인
3. 자동 저장 파일을 다른 이름으로 변경하여 보관 (예: `musinsa_1-150.xlsx`)
4. 프로그램 재실행
5. 다음 범위부터 수집 (예: 시작=151, 끝=300)
6. 수집 완료 후 엑셀 파일 수동 병합

### 실행 문제 해결

| 문제 | 해결 방법 |
|-----|---------|
| Windows Defender 경고 | "추가 정보" → "실행" 클릭 |
| 백신 차단 | 예외 등록 또는 일시 비활성화 |
| 브라우저 오류 | `playwright install chromium` 재실행 |
| output 폴더 없음 | exe와 같은 폴더에 자동 생성됨 |

---

## 파일 구조

### 빌드 전 (개발자)
```
collector/
├── app.py                 # 메인 GUI
├── config.py              # 설정
├── requirements.txt       # 의존성
├── collector.spec         # PyInstaller 설정
├── build_windows.bat      # 빌드 스크립트
├── collectors/            # 수집기 모듈
├── exporters/             # 출력 모듈
├── utils/                 # 유틸리티
└── data/                  # 데이터 파일
```

### 빌드 후 (배포)
```
배포 폴더/
├── ProductCollector.exe   # 실행 파일
├── install_browser.bat    # 브라우저 설치 스크립트
└── README.txt             # 사용자 안내
```

---

## 주의사항

1. **Playwright 브라우저는 exe에 포함되지 않습니다**
   - 사용자 PC에 별도 설치 필요
   - `install_browser.bat` 제공 권장

2. **Chrome 브라우저가 설치되어 있어야 합니다**
   - Playwright가 Chrome을 제어함

3. **출력 파일 위치**
   - exe 파일과 같은 폴더의 `output/` 폴더에 저장됨
   - 로그 파일: `logs/` 폴더

---

*작성일: 2026-01-26*
*수정일: 2026-01-30*
