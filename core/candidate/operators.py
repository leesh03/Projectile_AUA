"""Allowed, bounded migration operators for rule-guided recommendations."""

KEEP = "KEEP"
REMOVE = "REMOVE"
REDUCE = "REDUCE"
CONDITIONAL = "CONDITIONAL"
REPLACE_WITH_CODE = "REPLACE_WITH_CODE"

ALLOWED_OPERATORS = frozenset(
    {KEEP, REMOVE, REDUCE, CONDITIONAL, REPLACE_WITH_CODE}
)


def validate_operator(value: str) -> str:
    if value not in ALLOWED_OPERATORS:
        raise ValueError(
            f"unsupported candidate operator {value!r}; "
            f"allowed={sorted(ALLOWED_OPERATORS)}"
        )
    return value
