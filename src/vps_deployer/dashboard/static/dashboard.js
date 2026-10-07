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
let formEdited = false;
document.addEventListener("input", (event) => {
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) {
    formEdited = true;
  }
});
if (refreshRoot instanceof HTMLElement) {
  const seconds = Number(refreshRoot.getAttribute("data-refresh") || "0");
  if (seconds > 0) {
    window.setTimeout(() => {
      if (!formEdited) window.location.reload();
    }, seconds * 1000);
  }
}

const autoSubmitForm = document.querySelector("form[data-auto-submit]");
if (autoSubmitForm instanceof HTMLFormElement) {
  autoSubmitForm.submit();
}

document.querySelectorAll("input[data-filter]").forEach((input) => {
  input.addEventListener("input", () => {
    const container = document.getElementById(input.dataset.filter);
    const query = input.value.trim().toLowerCase();
    container?.querySelectorAll("[data-filter-row]").forEach((row) => {
      row.hidden = !row.textContent.toLowerCase().includes(query);
    });
  });
});

document.querySelector("[data-add-env]")?.addEventListener("click", () => {
  const fields = document.querySelector("[data-env-fields]");
  const row = fields.firstElementChild.cloneNode(true);
  row.querySelectorAll("input").forEach(input => { input.value = ""; });
  fields.append(row);
  row.querySelector("input").focus();
});

const repositorySelect = document.querySelector("[data-repository]");
if (repositorySelect) {
  const branchSelect = document.querySelector("[data-branch]");
  const status = document.querySelector("[data-repository-status]");
  const createButton = document.querySelector("[data-create-project]");
  const retryButton = document.querySelector("[data-retry-repositories]");
  let generation = 0;
  let repositories = [];
  const reset = (select, label) => {
    select.replaceChildren(new Option(label, ""));
    select.disabled = true;
  };
  const getJSON = async (url) => {
    const response = await fetch(url, {headers: {Accept: "application/json"}});
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(typeof payload.detail === "string" ? payload.detail : "Unable to load GitHub choices. Reload to retry.");
    }
    return response.json();
  };
  async function loadBranches() {
    const request = ++generation;
    createButton.disabled = true;
    reset(branchSelect, "Loading branches…");
    const repository = repositorySelect.value;
    if (!repository) {
      reset(branchSelect, "Choose a repository first");
      status.textContent = "Choose a repository.";
      return;
    }
    status.textContent = "Loading branches…";
    try {
      const payload = await getJSON(`/api/github/branches?repository=${encodeURIComponent(repository)}`);
      if (request !== generation) return;
      branchSelect.replaceChildren(...payload.branches.map(name => new Option(name, name)));
      branchSelect.disabled = !payload.branches.length;
      const defaultBranch = repositories.find(item => item.repository === repository)?.default_branch;
      if (payload.branches.includes(defaultBranch)) branchSelect.value = defaultBranch;
      createButton.disabled = !branchSelect.value;
      status.textContent = payload.branches.length ? "Repository and branch ready." : "This repository has no branches yet.";
    } catch (error) {
      if (request !== generation) return;
      reset(branchSelect, "Unable to load branches");
      status.textContent = error.message;
    }
  }
  async function loadRepositories() {
    const request = ++generation;
    createButton.disabled = true;
    retryButton.disabled = true;
    reset(repositorySelect, "Loading repositories…");
    reset(branchSelect, "Choose a repository first");
    status.textContent = "Loading GitHub repositories…";
    try {
      const payload = await getJSON("/api/github/repos");
      if (request !== generation) return;
      repositories = payload.repositories;
      repositorySelect.replaceChildren(new Option("Choose a repository", ""),
        ...repositories.map(item => new Option(item.repository, item.repository)));
      repositorySelect.disabled = !repositories.length;
      status.textContent = repositories.length ? "Choose a repository to load its branches." : "No repositories available. Grant repository access in GitHub settings, then reload.";
    } catch (error) {
      if (request !== generation) return;
      reset(repositorySelect, "Unable to load repositories");
      status.textContent = error.message;
    } finally {
      retryButton.disabled = false;
    }
  }
  repositorySelect.addEventListener("change", loadBranches);
  branchSelect.addEventListener("change", () => { createButton.disabled = !branchSelect.value; });
  retryButton.addEventListener("click", loadRepositories);
  loadRepositories();
}
