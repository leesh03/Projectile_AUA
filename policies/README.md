# policies — 우혁 담당

환불 정책 문서, Agent용 기계 판독 규칙, 독립 정답 판정 코드.

## 만들 파일
- `refund_policy_spec_v0.5.md`: 사람이 검토하는 규범 정책 원문
- `policy_rules.json`: pull된 Policy Agent가 읽는 `policy-rule-set-v1` 규칙
- `policy_oracle.py`: Gold 생성·검증용 독립 결정론 판정 함수
- `policy_text.json`: 기존 REFUND-01~05 호환 문서

## 브랜치
git checkout -b feat/dataset tester

## 주의
- oracle은 Agent와 **독립적으로** 구현합니다. 같은 잘못된 가정을 공유하면 정답이 오답이 됩니다.
- `policy_rules.json`과 Oracle은 60개 `policy_facts`에 대해 판정·조항이 같아야 합니다.
- 정책 문장 · oracle 코드 · 수작업 검토를 분리해서 교차 확인하세요.
- 정책 clause별 단위 테스트를 함께 만듭니다.
