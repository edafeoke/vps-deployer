document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const message = target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
  const copyId = target.getAttribute("data-copy");
  if (copyId) {
    const node = document.getElementById(copyId);
    const text = node?.textContent?.trim();
    if (text && navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        target.textContent = "Copied";
        window.setTimeout(() => {
          target.textContent = "Copy";
        }, 1600);
      });
    }
  }
});

const refreshRoot = document.querySelector("[data-refresh]");
if (refreshRoot instanceof HTMLElement) {
  const seconds = Number(refreshRoot.getAttribute("data-refresh") || "0");
  if (seconds > 0) {
    window.setTimeout(() => {
      window.location.reload();
    }, seconds * 1000);
  }
}

const autoSubmitForm = document.querySelector("form[data-auto-submit]");
if (autoSubmitForm instanceof HTMLFormElement) {
  autoSubmitForm.submit();
}
