# 버전 관리 및 다중 버전 동시 실행 가이드

> 작성일: 2026-03-23
> 목적: 신규 기능 추가 시 기존 기능 영향 없이 한 PC에서 여러 버전을 동시에 실행하기 위한 구조

---

## 배경

기능 추가·수정 중 기존에 정상 동작하던 기능이 중단되는 문제가 반복됨.
이를 방지하기 위해 버전별로 독립 실행 가능한 구조를 도입함.

---

## 구조 개요

버전 정보는 **`config.py` 한 곳에만** 선언하며, 나머지 파일은 이를 참조합니다.

```
config.py
  └── APP_VERSION = "1.1"          ← 버전 변경 시 여기만 수정
  └── APP_NAME    = "... v1.1"     ← 앱 타이틀 자동 반영
  └── OUTPUT_DIR  = output_v1.1/  ← 버전별 독립 출력 폴더
  └── LOGS_DIR    = logs_v1.1/    ← 버전별 독립 로그 폴더

app.py
  └── self.title(APP_NAME)         ← 윈도우 타이틀에 버전 자동 표시

collector.spec
  └── name = ProductCollector_v1.1.exe  ← 빌드 exe 이름에 버전 자동 포함
```

### 버전별 독립 폴더 구조

```
collector/
├── output_v1.1/    ← v1.1 실행 시 생성되는 엑셀 파일
├── output_v1.2/    ← v1.2 실행 시 생성되는 엑셀 파일
├── logs_v1.1/      ← v1.1 로그
├── logs_v1.2/      ← v1.2 로그
└── data/           ← 공통 데이터 (버전 공유)
```

---

## 새 버전 출시 절차

### 1. 새 기능 브랜치 생성

```bash
git checkout -b feature/기능명
```

### 2. 기능 개발 후 버전 번호 올리기

`config.py` 의 한 줄만 수정:

```python
APP_VERSION = "1.2"   # 1.1 → 1.2
```

### 3. 동작 확인

```bash
python app.py
# 앱 타이틀이 "상품 데이터 수집 프로그램 v1.2"인지 확인
```

### 4. Windows 실행 파일 빌드

```bash
python -m PyInstaller --clean collector.spec
# dist/ProductCollector_v1.2.exe 생성됨
```

### 5. 커밋 & 태그

```bash
git add -p
git commit -m "v1.2: 기능 설명"
git tag v1.2
git checkout main
git merge feature/기능명
```

---

## 한 PC에서 두 버전 동시 실행

1. `dist/ProductCollector_v1.1.exe` → 기존 안정 버전 실행
2. `dist/ProductCollector_v1.2.exe` → 신규 버전 테스트

두 프로세스가 서로 다른 output/logs 폴더를 사용하므로 파일 충돌 없음.
앱 타이틀바에 버전이 표시되므로 화면에서 즉시 구분 가능.

---

## 이전 버전으로 롤백

```bash
# 특정 태그로 되돌리기 (읽기 전용 확인)
git checkout v1.1

# 또는 브랜치로 복원
git checkout main
```

---

## 파일별 역할 요약

| 파일 | 역할 |
|------|------|
| `config.py` | 버전 정보 단일 선언 (`APP_VERSION`, `APP_NAME`) |
| `app.py` | `APP_NAME`을 윈도우 타이틀에 사용 |
| `collector.spec` | 정규식으로 `APP_VERSION` 읽어 exe 이름에 반영 |
| `collectors/base.py` | `OUTPUT_DIR`, `LOGS_DIR` 을 config에서 참조 (자동 버전 분리) |
| `exporters/excel.py` | `OUTPUT_DIR` 을 config에서 참조 (자동 버전 분리) |

---

## 주의사항

- `collector.spec`에서 버전을 읽을 때 `importlib` 대신 **정규식** 파싱 사용 (부작용 방지)
- `data/` 폴더는 버전 간 공유 (color_mapping 등 공통 데이터)
- 버전별 output 폴더는 자동 생성되므로 별도 생성 불필요
