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
    const text =
      node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement
        ? node.value
        : node?.textContent?.trim();
    if (text && navigator.clipboard) {
      navigator.clipboard.writeText(text).then(() => {
        target.textContent = "Copied";
        window.setTimeout(() => {
          target.textContent = "Copy";
        }, 1600);
      });
    }
  }
  const secretId = target.getAttribute("data-generate-secret");
  if (secretId) {
    const input = document.getElementById(secretId);
    if (input instanceof HTMLInputElement && window.crypto) {
      const bytes = new Uint8Array(32);
      window.crypto.getRandomValues(bytes);
      input.value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
      input.type = "text";
      target.textContent = "Generated";
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
