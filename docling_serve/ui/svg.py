from pyjsx import JSX


def _tag(name: str):
    def factory(children, **args) -> JSX:
        props = " ".join([f'{k}="{v}"' for k, v in args.items()])

        if children:
            child_renders = "".join([f"{c}" for c in children])
            return f"<{name} {props}>{child_renders}</{name}>"
        else:
            return f"<{name} {props} />"

    return factory


circle = _tag("circle")
clipPath = _tag("clipPath")
defs = _tag("defs")
foreignObject = _tag("foreignobject")
image = _tag("image")
path = _tag("path")
rect = _tag("rect")
text = _tag("text")
use = _tag("use")
