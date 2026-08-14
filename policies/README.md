# policies — 우혁 담당

환불 정책 문서와 정답 판정 코드.

## 만들 파일
policy_text.json   (REFUND-01~05: 기본 기간, 전자제품 개봉 예외, Premium 연장,
                    Final Sale 예외, 회사 귀책)
policy_oracle.py   (파이썬 결정론 판정 함수)

## 브랜치
git checkout -b feat/dataset tester

## 주의
- oracle은 Agent와 **독립적으로** 구현합니다. 같은 잘못된 가정을 공유하면 정답이 오답이 됩니다.
- 정책 문장 · oracle 코드 · 수작업 검토를 분리해서 교차 확인하세요.
- 정책 clause별 단위 테스트를 함께 만듭니다.
