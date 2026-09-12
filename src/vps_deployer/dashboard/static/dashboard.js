document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) {
    return;
  }
  const message = target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) {
    event.preventDefault();
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
