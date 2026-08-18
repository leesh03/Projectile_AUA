# Data Changelog

정책, 데이터베이스 또는 Gold TestCase를 변경할 때 영향 범위와 판정 변경 사유를
기록합니다. 같은 정책·DB·TestCase 버전은 항상 같은 평가 입력과 Gold를 가리켜야
합니다.

## 2026-08-18 — v0.5 경로 정규화 및 보호 산출물 복구

### 변경 내용

- `shop.db`, `agent_cases.json`, `test_cases.json`을 생성기와 문서가 정의한
  `data/` 경로로 통일했습니다.
- 다운로드 중복 이름인 `test_cases(1).json`을 `test_cases.json`으로 바로잡고,
  내용이 동일한 `policies/test_cases.json` 중복본을 제거했습니다.
- 데이터 생성기를 `data/build_answer_data.py`, 검증 코드를
  `tests/test_dataset.py`에 배치했습니다.
- 보호 정답 원장 `data/answer_key.db`와 전체 산출물 manifest를 재생성했습니다.
- 현재 환경에는 Python 실행기가 없어 보호 정답 원장은 동일한 DDL과 Gold JSON을
  사용해 Windows SQLite 3.51.1로 복구했으며, 해당 버전을 release manifest에
  별도로 기록했습니다. 정식 baseline freeze 전 canonical Python 생성기를 다시
  실행해 재현성을 최종 확인해야 합니다.

### Gold 영향

- TestCase 수와 난이도 분포는 20개(Easy 6 / Medium 8 / Hard 6)로 유지됩니다.
- G-019의 불일치 증거 사례는 `required_fields`에서 증거 provenance 네 필드를
  제거하고 `/shipment/issue_code`만 요구합니다.
- G-019의 Gold decision은 `NEED_MORE_INFO`, primary clause는 `POL-40.04`로
  유지되므로 판정 결과 변경은 없습니다.

### 검토 상태

- GOLD-10 시나리오 교차 확인: `PASSED`
- 독립적 사람 검토: `PENDING`
