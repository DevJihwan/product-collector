# Windows 빌드 및 배포 트러블슈팅 가이드

## 개요

이 문서는 GitHub Actions를 통한 Windows EXE 빌드 및 배포 과정에서 발생했던 문제와 해결 방법을 정리합니다.
향후 동일한 오류가 재발하지 않도록 원인, 해결책, 체크리스트를 기록합니다.

---

## 발생했던 문제 목록

### 1. Playwright 브라우저 버전 불일치

**증상**
```
Looks like Playwright was just installed or updated.
Please run the following command to download new browsers:
    playwright install
```
EXE 실행 시 위 오류가 표시되며 브라우저 자동화가 동작하지 않음.

**원인**
- Playwright는 버전마다 요구하는 Chromium 리비전(빌드 번호)이 다름
- GitHub Actions에서 EXE를 빌드할 때 사용된 Playwright 버전 ≠ 사용자 PC에 설치된 Playwright 버전
- 예: EXE에 번들된 Playwright가 chromium-1140을 요구하는데, 사용자 PC에는 chromium-1208이 설치되어 있으면 실패

**해결**
- `requirements.txt`에서 Playwright 버전을 **정확히 고정** (`playwright==1.50.0`)
- `install_browser.bat`에서도 **동일한 버전**을 명시 (`pip install playwright==1.50.0`)
- 사용자는 EXE 실행 전 반드시 `install_browser.bat`을 실행하여 일치하는 브라우저 설치

**관련 파일**
- `requirements.txt` — 버전 고정
- `install_browser.bat` — 사용자측 브라우저 설치 스크립트
- `app.py` 상단 — `PLAYWRIGHT_BROWSERS_PATH` 환경 변수 설정 (`%LOCALAPPDATA%\ms-playwright`)

**재발 방지 규칙**
> Playwright 버전을 올릴 때는 반드시 `requirements.txt`와 `install_browser.bat` 두 곳을 동시에 수정하고, 새 EXE를 배포할 때 install_browser.bat도 함께 배포할 것.

---

### 2. UPX 압축 시 MSVC++ 런타임 DLL 손상

**증상**
- EXE가 빌드는 성공하지만 실행 시 크래시 또는 DLL 로드 실패
- `vcruntime140.dll` 관련 오류 메시지

**원인**
- PyInstaller의 `upx=True` 옵션이 모든 바이너리를 UPX 압축
- MSVC++ 런타임 DLL(`vcruntime140.dll`, `msvcp140.dll` 등)은 UPX 압축 시 손상됨
- GitHub Actions의 `windows-latest` 러너는 Visual Studio가 설치되어 있어 해당 DLL이 번들에 포함됨

**해결**
- `collector.spec`의 `upx_exclude`에 MSVC++ 런타임 DLL 목록 추가:
```python
upx_exclude=[
    'vcruntime140.dll',
    'vcruntime140_1.dll',
    'msvcp140.dll',
    'msvcp140_1.dll',
    'msvcp140_2.dll',
    'ucrtbase.dll',
    'api-ms-win-*.dll',
],
```

**관련 파일**
- `collector.spec` — PyInstaller 빌드 설정

**재발 방지 규칙**
> 새로운 DLL 의존성이 추가되면 UPX 압축 호환 여부를 확인할 것. 시스템 런타임 DLL은 기본적으로 `upx_exclude`에 포함할 것.

---

## 빌드 아키텍처 이해

### 빌드 환경 vs 실행 환경

```
┌─────────────────────────────────┐     ┌─────────────────────────────────┐
│   GitHub Actions (빌드 환경)      │     │   사용자 Windows PC (실행 환경)    │
│                                 │     │                                 │
│  Python 3.11                    │     │  Python 3.11 (필수)              │
│  playwright==1.50.0             │     │  playwright==1.50.0 (필수)       │
│  PyInstaller → EXE 생성          │     │  Chromium (playwright install)  │
│                                 │     │                                 │
│  EXE에 포함되는 것:               │     │  EXE에 포함되지 않는 것:          │
│  ├ Python 런타임                 │     │  └ Chromium 브라우저              │
│  ├ 모든 Python 패키지             │     │    (%LOCALAPPDATA%\ms-playwright)│
│  ├ Playwright 라이브러리          │     │                                 │
│  ├ 프로젝트 코드                  │     │                                 │
│  └ data/color_mapping.json      │     │                                 │
└─────────────────────────────────┘     └─────────────────────────────────┘
```

핵심: **Chromium 브라우저는 EXE에 포함되지 않는다.** 사용자 PC에 별도 설치 필요.

### 버전 동기화 체인

```
requirements.txt (playwright==X.Y.Z)
        │
        ├──→ GitHub Actions 빌드 시 설치 → EXE에 번들
        │
        └──→ install_browser.bat (playwright==X.Y.Z) → 사용자 PC에 설치
                    │
                    └──→ playwright install chromium → 매칭되는 Chromium 설치
```

세 지점의 버전이 일치하지 않으면 오류 발생.

---

## Playwright 버전 업그레이드 절차

Playwright를 업그레이드해야 할 경우 아래 순서를 따릅니다:

1. **`requirements.txt` 수정**
   ```
   playwright==1.XX.0   ← 새 버전으로 변경
   ```

2. **`install_browser.bat` 수정**
   ```bat
   python -m pip install playwright==1.XX.0   ← 동일 버전
   ```

3. **로컬 테스트**
   ```bash
   pip install playwright==1.XX.0
   playwright install chromium
   python app.py  # GUI 정상 동작 확인
   ```

4. **커밋 & Push** → GitHub Actions 자동 빌드

5. **빌드 결과 확인** → Actions 탭에서 성공 여부 확인

6. **배포** → Artifact ZIP에 EXE + install_browser.bat 포함 확인

---

## 배포 전 체크리스트

EXE를 사용자에게 전달하기 전 확인할 사항:

- [ ] `requirements.txt`의 playwright 버전이 고정되어 있는가 (`==` 사용)
- [ ] `install_browser.bat`의 playwright 버전이 `requirements.txt`와 동일한가
- [ ] GitHub Actions 빌드가 성공했는가
- [ ] Artifact ZIP에 `ProductCollector.exe`, `install_browser.bat`, `README.txt`가 모두 포함되어 있는가
- [ ] `collector.spec`의 `upx_exclude`에 시스템 런타임 DLL이 포함되어 있는가
- [ ] 실제 Windows 환경에서 `install_browser.bat` → `ProductCollector.exe` 순서로 테스트했는가

---

## 사용자 배포 안내 (전달용)

```
1. Python 3.11 설치
   - https://www.python.org/downloads/
   - 설치 시 "Add Python to PATH" 반드시 체크

2. install_browser.bat 실행 (최초 1회)
   - 브라우저 자동 설치됨

3. ProductCollector.exe 실행
```

---

## 관련 파일 참조

| 파일 | 역할 |
|------|------|
| `requirements.txt` | Python 의존성 및 Playwright 버전 고정 |
| `collector.spec` | PyInstaller 빌드 설정 (UPX 제외 목록 포함) |
| `.github/workflows/build-windows.yml` | GitHub Actions 빌드 워크플로우 |
| `install_browser.bat` | 사용자측 Playwright 브라우저 설치 스크립트 |
| `app.py` (상단) | EXE 실행 시 브라우저 경로 환경 변수 설정 |
