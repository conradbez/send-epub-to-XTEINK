// Click anything with [data-copy] to copy. A bare attribute copies the
// element's own text; an attribute with a value copies that instead — the big
// Copy buttons carry the catalog URL so the button itself can just say "Copy".
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-copy]");
  if (!target) return;
  const text = target.dataset.copy || target.textContent.trim();
  const done = () => {
    target.classList.add("copied");
    if (target.dataset.copy) {
      if (!target.dataset.label) target.dataset.label = target.textContent;
      target.textContent = "Copied";
    }
    clearTimeout(target.copyTimer);
    target.copyTimer = setTimeout(() => {
      target.classList.remove("copied");
      if (target.dataset.label) target.textContent = target.dataset.label;
    }, 1400);
  };
  if (navigator.clipboard) {
    navigator.clipboard.writeText(text).then(done, () => {});
  } else {
    const field = document.createElement("textarea");
    field.value = text;
    document.body.appendChild(field);
    field.select();
    document.execCommand("copy");
    field.remove();
    done();
  }
});
