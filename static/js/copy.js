// Click any <code data-copy> to copy it. Device passwords get typed on a
// keyboard-less reader; the fewer transcription errors the better.
document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-copy]");
  if (!target) return;
  const text = target.textContent.trim();
  const done = () => {
    const previous = target.dataset.label || target.textContent;
    target.dataset.label = previous;
    target.classList.add("copied");
    setTimeout(() => target.classList.remove("copied"), 1200);
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
