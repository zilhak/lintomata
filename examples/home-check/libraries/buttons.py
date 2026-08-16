"""라이브러리 — **"무엇이 버튼인가" 를 판정하는 함수의 본체는 하나여야 한다.**

`schema.md` 6.5절이 든 바로 그 예다. 이 프로젝트에는 버튼을 지각하는 스크립트가
넷 있다 — 값 검증용 하나(`perceive_buttons.py`)와 비교용 셋(`cmp_buttons_*.py`).
넷이 각자 HTML 을 훑는 코드를 따로 갖고 있으면 **라벨 정규화 규칙이 갈리는 순간
개념 층 비교가 조용히 거짓이 된다** — 같은 버튼인데 `"문서 보기"` 와
`"문서  보기"` 로 갈리는 식이다.

**형제 파일 `import` 는 되지 않는다.** 등록하면 스크립트 파일 하나만 복사되므로
옆 파일은 따라오지 않는다. 그래서 공유는 **등록소를 통해서** 한다:

    lintomata library add libraries/buttons.py       # 본체를 등록하고
    노드 JSON 의 "libraries" 에 그 id 를 적고                # 노드가 배선하고
    from lintomata_lib import buttons                 # 스크립트가 쓴다

(여기 참조 문법을 예시로 그대로 적지 않는 이유가 있다 — 등록소는 **파일 내용에서**
참조 문법을 긁어 참조 그래프를 만들므로, 설명으로 적은 것도 참조로 잡힌다.)

**여기를 고치면 이것을 쓰는 노드·파이프라인·Spec 의 검증이 전부 무효화된다.**
그게 *"본체가 한 곳에 있다"* 가 실제로 의미를 갖는 이유다.

⚠ v1 의 라이브러리는 **함수만** 제공한다. `dataclass` 는 쓰는 쪽 스크립트에 둔다
(노드 간 계약 타입이 스크립트 밖에서 생기면 타입 레지스트리에 구멍이 난다).
"""

from html.parser import HTMLParser


def normalize(text):
    """라벨 정규화 — 줄바꿈·연속 공백을 하나로 접는다.

    **비교 파이프라인의 전제가 이것이다.** 마크업이 완전히 달라도 개념이 같으면
    통과해야 하는데, 들여쓰기 차이가 라벨에 남으면 개념이 다르다고 판정된다.
    """
    return " ".join(text.split())


def is_button(tag, attrs):
    """**이 프로젝트의 도메인 지식.** `<button>` 이 있다고 그게 버튼인 게 아니다.

    - `<button>` 태그이면 버튼이다
    - `role="button"` 이면 버튼이다 (마크업이 `div`/`a` 여도 사람에겐 버튼이다)
    - 단 `data-decoy="true"` 는 **누를 수 있게 생긴 배경 장식**이라 버튼이 아니다
    """
    if attrs.get("data-decoy") == "true":
        return False
    return tag == "button" or attrs.get("role") == "button"


def collect(html, match):
    """`match(tag, attrs)` 가 참인 요소의 라벨을 문서 순서대로 모은다.

    무엇을 버튼으로 볼지는 **부르는 쪽이 정한다** — 비교 파이프라인은 대상마다
    인식 규칙이 다르고(시맨틱/클래스/role), 그게 설계다. 여기서 공유하는 것은
    *훑는 방법과 라벨 정규화* 이지 *무엇이 버튼인가* 가 아니다.
    """
    reader = _LabelReader(match)
    reader.feed(html)
    reader.close()
    return reader.labels


class _LabelReader(HTMLParser):
    """버튼으로 인정된 요소의 텍스트만 모은다. 중첩 태그를 깊이로 센다."""

    def __init__(self, match):
        super().__init__(convert_charrefs=True)
        self.labels = []
        self._match = match
        self._depth = 0
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        if self._depth > 0:
            self._depth += 1
            return
        table = {name: (value or "") for name, value in attrs}
        if self._match(tag, table):
            self._depth = 1
            self._buffer = []

    def handle_endtag(self, tag):
        if self._depth == 0:
            return
        self._depth -= 1
        if self._depth == 0:
            self.labels.append(normalize("".join(self._buffer)))

    def handle_data(self, data):
        if self._depth > 0:
            self._buffer.append(data)
