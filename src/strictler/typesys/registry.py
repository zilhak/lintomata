"""dataclass 등록기 — 집합 정규화, 부분집합 병합, 그래프 검사용 동일성 판정.

`schema.md` 7절이 근거다. 이름이 `registry` 지만 **등록소(`strictler.store`)와 무관하다** —
이건 *타입 등록기*다.

**엔진은 구성 시점에 모든 dataclass 를 등록하고 집합 검사를 전체에 건다.**
각 dataclass 를 **`(필드명, 타입)` 쌍의 집합**으로 다루면 별도 규칙이 필요 없어진다:

| | 왜 규칙이 필요 없나 |
|---|---|
| 필드 순서 | 집합이므로 애초에 의미가 없다 |
| 이름만 vs 이름+타입 | 원소가 `(이름, 타입)` 쌍이므로 자동 |
| 중첩 dataclass | 중첩 필드 타입도 등록된 dataclass 이므로 **위상 정렬해 바닥부터 정규화**하면 재귀가 저절로 된다 |

**병합 단위: 부분집합 격자의 연결 성분 전체를 합집합으로 병합한다.**
`A ⊂ B`, `A ⊂ C`, `B`·`C` 무관 — "가장 큰 것"이 유일하지 않지만, **그래프 검사가
선언된 정의로 이뤄지므로 어느 쪽으로 병합해도 정확성에 영향이 없다.** 연결 성분을
통째로 합집합 내면 모호함 자체가 생기지 않고 잃는 것도 없다.

⚠ 오배선 탐지력이 약해지는 것은 **감수한다**. `ButtonCount(count:int)` 와
`MenuCount(count:int)` 는 동일하다. 배선은 파이프라인 JSON 에 노드 id 로 명시적으로
쓰므로 타입 검사가 잡아주길 기대할 실수가 아니고, 값의 의미는 Reckon 이 잡는다.

⚠ stub. Step 1 에서 구현한다.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from strictler.typesys.primitives import TypeRef

__all__ = ["FieldSpec", "DataclassSpec", "TypeRegistry"]


class FieldSpec:
    """dataclass 필드 하나. 필드: `name`, `type`(`TypeRef`)."""

    def __init__(self, name: str, type: TypeRef) -> None:
        raise NotImplementedError("Step 1에서 구현")


class DataclassSpec:
    """스크립트가 선언한 dataclass 하나.

    필드: `name`, `fields`(`tuple[FieldSpec, ...]`), `origin`(어느 스크립트에서 왔는지).
    """

    def __init__(self, name: str, fields: tuple[FieldSpec, ...], origin: str = "") -> None:
        raise NotImplementedError("Step 1에서 구현")


class TypeRegistry:
    """모든 노드의 dataclass 선언을 모아 집합 검사를 거는 등록기.

    사용 순서: `register()` 를 전부 부른 뒤 `normalize()` 한 번 → 이후 조회.
    """

    def register(self, spec: DataclassSpec) -> None:
        """dataclass 선언 하나를 등록한다. 같은 이름이 다른 정의로 오면 오류."""
        raise NotImplementedError("Step 1에서 구현")

    def normalize(self) -> None:
        """위상 정렬해 **바닥부터** 정규화한다. 중첩 dataclass 가 여기서 재귀적으로 풀린다.

        순환 참조(A 가 B 를, B 가 A 를 필드로)가 있으면 오류.
        """
        raise NotImplementedError("Step 1에서 구현")

    def field_set(self, name: str) -> frozenset[tuple[str, str]]:
        """정규화된 `(필드명, 타입표기)` 쌍의 집합. 모든 비교의 기반이다."""
        raise NotImplementedError("Step 1에서 구현")

    def same_definition(self, a: str, b: str) -> bool:
        """**그래프 검사용 — 엄격한 동일성.** 두 필드 집합이 완전히 같은가.

        파이프라인 배선 검사(`STR-TYPE-004`)가 이걸 쓴다.
        """
        raise NotImplementedError("Step 1에서 구현")

    def is_subset(self, a: str, b: str) -> bool:
        """`a` 의 필드 집합이 `b` 의 부분집합인가. 병합 대상 판정용."""
        raise NotImplementedError("Step 1에서 구현")

    def merge_components(self) -> dict[str, str]:
        """부분집합 격자의 **연결 성분 전체를 합집합**으로 병합한다.

        반환: `{원래 이름: 병합 클래스 이름}`. 런타임 표현 층에서만 쓰인다 —
        그래프 검사는 여전히 선언된 정의로 한다.
        """
        raise NotImplementedError("Step 1에서 구현")

    def build_model(self, name: str) -> type[BaseModel]:
        """이름에 해당하는(병합된) 타입의 pydantic 모델을 만든다.

        **pydantic 경계 검증이 실제 값을 만나는 자리**는 노드 단위테스트와
        엔진의 input/output 검증 둘뿐이다 (`schema.md` 14절).

        병합 클래스의 여분 필드는 비어 있을 수 있다 — 그건 **표현 층의 구현
        디테일(미설정 센티널)**이지 스크립트가 선언하는 타입에 `Optional` 이
        들어가는 게 아니다. 그 필드를 읽는 노드는 그 필드를 채우는 노드하고만
        연결된다는 것을 그래프 검사가 이미 보장했다.
        """
        raise NotImplementedError("Step 1에서 구현")

    def to_value(self, name: str, raw: Any) -> Any:
        """JSON 원값을 그 타입의 인스턴스로 만든다. 단위테스트 fixture 와 리포트가 쓴다."""
        raise NotImplementedError("Step 1에서 구현")
