from pyjsx import JSX, jsx  # type: ignore


def _tag(name: str):
    def factory(*, children: list[JSX] = [], **props) -> JSX:
        return jsx(name, props, children)

    return factory


image = _tag("image")
path = _tag("path")
rect = _tag("rect")
text = _tag("text")
