// Propagate URL hash to CSS target class for elements with the same id or data-id.
window.addEventListener("hashchange", function (event) {
  [
    ["remove", "oldURL"],
    ["add", "newURL"],
  ].forEach(([op, tense]) => {
    const hash = new URL(event[tense]).hash.slice(1);
    document
      .querySelectorAll(`[data-id="${hash}"], [id="${hash}"], [href="${hash}"]`)
      .forEach((el) => el.classList[op]("target"));
  });
});

// Navigate document items with cursor keys.
document.addEventListener("keydown", function (event) {
  const target = document.querySelector("*:target");
  const tbounds = target?.getBoundingClientRect();
  const filters = {
    ArrowUp: (_x, y) => y < tbounds.top,
    ArrowDown: (_x, y) => y > tbounds.bottom,
    ArrowLeft: (x, _y) => x < tbounds.left,
    ArrowRight: (x, _y) => x > tbounds.right,
  };

  if (target && filters[event.key]) {
    const elements = [...document.querySelectorAll(".item[id], .item *[id]")];

    let minEl, minDist;
    for (const el of elements) {
      const elBounds = el.getBoundingClientRect();

      if (
        filters[event.key](
          (elBounds.left + elBounds.right) / 2,
          (elBounds.top + elBounds.bottom) / 2
        )
      ) {
        const elDist =
          Math.abs(tbounds.x - elBounds.x) + Math.abs(tbounds.y - elBounds.y);

        if (el != target && elDist < (minDist ?? Number.MAX_VALUE)) {
          minEl = el;
          minDist = elDist;
        }
      }
    }

    if (minEl) {
      event.preventDefault();
      location.href = `#${minEl.id}`;
    }
  }
});

// Navigate to item with id when it is clicked.
function clickId(e) {
  e.stopPropagation();
  const id = e.currentTarget.getAttribute("data-id") ?? e.currentTarget.id;
  location.href = `#${id}`;
}

window.onload = () => {
  // (Re-)set the value of input[data-dep-on] to conform to a value of another input[name="data-dep-on"].
  document.querySelectorAll("input[dep-on]").forEach((element) => {
    const onName = element.getAttribute("dep-on");
    const onElement = document.getElementsByName(onName)[0];
    const depMap = JSON.parse(element.getAttribute("dep-values") ?? "{}");

    if (onElement && depMap) {
      // On load.
      element.value = depMap[onElement.value] ?? "";

      // On change.
      onElement.addEventListener(
        "change",
        (event) => (element.value = depMap[event.currentTarget.value] ?? "")
      );
    }
  });

  // Toggle display of input[data-display-when] when it requires a different input[type=checkbox] to be checked.
  document.querySelectorAll("*[display-when]").forEach((element) => {
    const whenElements = element
      .getAttribute("display-when")
      .split(",")
      .flatMap((whenName) => [...document.getElementsByName(whenName.trim())]);

    function update() {
      const allChecked = whenElements.every((el) => el.checked);
      element.classList[allChecked ? "remove" : "add"]("hidden");
    }

    // On load.
    update();

    // On change.
    whenElements.forEach((whenElement) =>
      whenElement.addEventListener("change", update)
    );
  });

  // Persist input value in local storage.
  document
    .querySelectorAll("input[type=checkbox][persist]")
    .forEach((element) => {
      const prefix = element.getAttribute("persist");
      const name = element.getAttribute("name");
      const key = `docling-serve-${prefix}-${name}`;

      element.checked = localStorage.getItem(key) === "true";
      element.addEventListener("change", (event) =>
        localStorage.setItem(key, event.target.checked)
      );
    });
};
