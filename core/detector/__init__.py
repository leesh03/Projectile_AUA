"""L4 — 규칙 탐지기. `rules` 모듈을 여기서 임포트해야 @register 데코레이터가 실행되고
REGISTRY/DEFAULT_RULES가 채워진다 — 이 패키지를 통해서만 쓰도록 한다.
"""

from core.detector import rules as _rules  # noqa: F401  (등록 부수효과 때문에 임포트)
from core.detector.base import DetectionContext, Rule, SkippedRule, run_rules
from core.detector.rules import DEFAULT_RULES
from core.detector.verdict import decide_verdict

__all__ = ["DEFAULT_RULES", "DetectionContext", "Rule", "SkippedRule", "decide_verdict", "run_rules"]
