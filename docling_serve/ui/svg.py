from pyjsx import JSX  # type: ignore


def _tag(name: str):
    def factory(children, **args) -> JSX:
        props = " ".join([f'{k}="{v}"' for k, v in args.items()])

        if children:
            child_renders = "".join([str(c) for c in children])
            return f"<{name} {props}>{child_renders}</{name}>"
        else:
            return f"<{name} {props} />"

    return factory


image = _tag("image")
path = _tag("path")
rect = _tag("rect")
text = _tag("text")
