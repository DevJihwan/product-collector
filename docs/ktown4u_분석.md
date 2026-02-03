# Ktown4u 사이트 분석

---

**분석일:** 2026-01-30
**대상 URL:** https://kr.ktown4u.com/searchList?goodsTextSearch=BLACKPINK
**사이트 유형:** K-POP 앨범/굿즈 전문 쇼핑몰

---

## 1. 사이트 기본 정보

| 항목 | 내용 |
|------|------|
| **사이트** | kr.ktown4u.com |
| **기술 스택** | Next.js (React SSR) |
| **데이터 제공 방식** | `__NEXT_DATA__` JSON (서버 사이드 렌더링) |
| **언어 지원** | 한국어, 영어, 중국어, 일본어 |

---

## 2. URL 구조

### 2.1 검색 결과 페이지

```
https://kr.ktown4u.com/searchList?goodsTextSearch={검색어}
https://kr.ktown4u.com/searchList?goodsTextSearch={검색어}&page={페이지번호}
```

**예시:**
- `https://kr.ktown4u.com/searchList?goodsTextSearch=BLACKPINK`
- `https://kr.ktown4u.com/searchList?goodsTextSearch=BLACKPINK&page=2`

### 2.2 상품 상세 페이지

```
https://kr.ktown4u.com/iteminfo?goods_no={상품번호}
```

**예시:**
- `https://kr.ktown4u.com/iteminfo?goods_no=155644`

---

## 3. 데이터 구조

### 3.1 목록 페이지 데이터 위치

Next.js SSR 페이지로, HTML 내 `<script id="__NEXT_DATA__">` 태그에 JSON 데이터가 포함됨.

```
__NEXT_DATA__.props.pageProps.result.data  # 상품 목록 배열
__NEXT_DATA__.props.pageProps.result       # 페이지네이션 정보
```

### 3.2 상품 목록 필드 (result.data 배열)

| 필드명 | 타입 | 설명 | 예시 값 |
|--------|------|------|---------|
| `goodsNo` | number | 상품 고유 번호 | 155644 |
| `goodsNm` | string | 상품명 | "블랙핑크 미니앨범 3집 [DEADLINE]" |
| `grpNo` | number | 그룹/아티스트 번호 | 1741898 |
| `grpNm` | string | 그룹/아티스트명 | "BLACKPINK" |
| `kindNm` | string | 상품 종류 | "CD/LP", "DVD/BD", "굿즈" |
| `goodsKindCd` | string | 상품 종류 코드 | "general" |
| `dispPrice` | number | 정가 | 27500 |
| `dispDcPrice` | number | 할인가 | 22300 |
| `imgPath` | string | 이미지 URL | "https://cdn.ktown4u.com/..." |
| `saleYn` | string | 판매 여부 | "Y" / "N" |
| `goodsTotSale` | number | 누적 판매량 | 23108 |
| `releaseDt` | string | 출시일 | "2026-02-27" |
| `regDt` | string | 등록일 | - |
| `categoryPath` | string | 카테고리 경로 | "3675.107931.1723449..." |
| `shopNo` | number | 샵 번호 | 174 |
| `sellQtyHideYn` | string | 판매수량 숨김 여부 | "Y" / "N" |
| `onlineEventYn` | string | 온라인 이벤트 여부 | "Y" / "N" |
| `isAdult` | boolean | 성인 상품 여부 | false |

### 3.3 페이지네이션 정보 (result 객체)

| 필드명 | 타입 | 설명 | 예시 값 |
|--------|------|------|---------|
| `currentPage` | number | 현재 페이지 | 1 |
| `pageRange` | number | 총 페이지 수 | 22 |
| `categoryTotalCount` | number | 총 상품 수 | 430 |
| `next` | boolean | 다음 페이지 존재 여부 | true |

---

## 4. 상세 페이지 데이터

상품 상세 페이지(`/iteminfo?goods_no=...`)에서 추가로 수집 가능한 정보:

### 4.1 기본 정보

- 상세 상품명
- 정가 / 할인가 / 할인율
- 마일리지 적립 정보
- 재고 상태

### 4.2 옵션 정보

- 버전 선택 (예: BLACK Ver., SILVER Ver.)
- 특전 옵션 (포토카드 종류 등)
- 옵션별 추가 가격

### 4.3 구성품 정보

```
예시 (앨범 구성품):
- 포토북 (72페이지, 192×260×18mm)
- CD (120×120mm)
- 셀피 포토카드 (4종, 55×85mm)
- 포토 스티커 (4종, 60×90mm)
- 그래픽 스티커 (104×25mm)
- 단체 접지 포스터 (400×240mm)
```

### 4.4 상품 속성

| 항목 | 예시 |
|------|------|
| 출시일 | 2026-02-27 |
| 제조/수입 | 와이지플러스 |
| 원산지 | Korea |
| 배송비 | ₩3,000 (3만원 이상 무료) |

### 4.5 이미지

- 메인 이미지 (썸네일)
- 추가 이미지 (t1, t2 버전 등)
- 상세 설명 이미지

### 4.6 리뷰 정보

- 리뷰 개수
- 평점 (있는 경우)

---

## 5. 페이지네이션 상세

| 항목 | 값 |
|------|-----|
| **페이지당 상품 수** | 20개 (고정) |
| **페이지 파라미터** | `page=1, 2, 3...` (1부터 시작) |
| **최대 페이지** | `result.pageRange` 값 참조 |
| **방식** | 페이지 번호 기반 (무한 스크롤 아님) |

---

## 6. 정렬 옵션

검색 결과 페이지에서 지원하는 정렬 옵션:

| 옵션 | 설명 |
|------|------|
| 신상품순 | 최신 등록순 (기본값) |
| 인기상품순 | 판매량 기준 |
| 낮은가격순 | 가격 오름차순 |
| 높은가격순 | 가격 내림차순 |
| 프리오더 상품 | 예약 판매 상품만 |
| 품절상품제외 | 재고 있는 상품만 |

---

## 7. 상품 카테고리 종류

Ktown4u에서 판매하는 주요 상품 종류:

| kindNm | 설명 |
|--------|------|
| CD/LP | 음반 (앨범, 싱글) |
| DVD/BD | 영상물 (콘서트, 화보집) |
| 굿즈 | 공식 굿즈 (포토카드, 응원봉 등) |
| 잡지 | 화보집, 매거진 |
| 의류 | 공식 의류 |

---

## 8. 기존 수집기와 비교

| 항목 | Ktown4u | 무신사 | 네이버 스마트스토어 |
|------|---------|--------|---------------------|
| **데이터 소스** | `__NEXT_DATA__` JSON | DOM + JavaScript | API Response (JSON) |
| **목록 수집** | JSON 파싱 | DOM 파싱 + API 캡처 | API 응답 파싱 |
| **상세 수집** | JSON 파싱 | DOM 파싱 | API 응답 파싱 |
| **옵션 정보 위치** | 상세 페이지 | 상세 페이지 | 상세 페이지 |
| **페이지네이션** | page 파라미터 | 무한스크롤/페이지 | page 파라미터 |
| **인증 필요** | 없음 | 없음 | 없음 |
| **브라우저 필요** | 권장 (JS 렌더링) | 필수 | 불필요 (API 직접 호출 가능) |

---

## 9. 수집기 개발 시 고려사항

### 9.1 장점

1. **구조화된 데이터**: Next.js SSR로 `__NEXT_DATA__`에 모든 데이터가 JSON 형태로 제공
2. **명확한 필드명**: goodsNo, grpNm 등 의미가 명확한 필드명 사용
3. **API 캡처 불필요**: DOM에서 JSON 파싱만으로 수집 가능
4. **페이지네이션 정보 제공**: 총 페이지 수, 총 상품 수가 응답에 포함

### 9.2 주의사항

1. **옵션 정보**: 버전, 특전 등 옵션 정보는 상세 페이지 방문 필요
2. **다양한 상품 종류**: CD, DVD, 굿즈, 잡지 등 상품 유형이 다양함
3. **아티스트 정보**: 브랜드 대신 `grpNm` (그룹/아티스트명) 필드 사용
4. **검색 기반**: 카테고리 URL보다 검색 URL 사용이 더 안정적

### 9.3 권장 수집 방식

```
1단계: 검색 URL 접근
  → https://kr.ktown4u.com/searchList?goodsTextSearch={검색어}

2단계: __NEXT_DATA__ JSON 파싱
  → document.querySelector('#__NEXT_DATA__').textContent
  → JSON.parse() → props.pageProps.result

3단계: 페이지네이션 처리
  → result.pageRange (총 페이지 수) 확인
  → page=1, 2, 3... 순차 요청

4단계: 상세 페이지 수집 (선택)
  → /iteminfo?goods_no={goodsNo}
  → 옵션, 구성품, 상세 이미지 수집
```

---

## 10. 예상 엑셀 출력 형식

수집 시 권장하는 컬럼 구조:

| 컬럼명 | 소스 | 설명 |
|--------|------|------|
| Product_SKU | goodsNo | 상품 고유 번호 |
| Product_Name | goodsNm | 상품명 |
| Artist | grpNm | 아티스트/그룹명 |
| Category | kindNm | 상품 종류 (CD/LP, 굿즈 등) |
| Price | dispPrice | 정가 |
| Sale_Price | dispDcPrice | 할인가 |
| Sales_Count | goodsTotSale | 누적 판매량 |
| Release_Date | releaseDt | 출시일 |
| Sale_Status | saleYn | 판매 여부 |
| Image_URL | imgPath | 대표 이미지 |
| URL | (생성) | 상품 URL |
| Search_URL | (입력값) | 검색 URL |

---

*분석 완료: 2026-01-30*
