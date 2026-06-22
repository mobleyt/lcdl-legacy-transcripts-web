// Load the Aviary collection list and wire up the submit form.
const select = document.getElementById("collection");
const titleField = document.getElementById("collection_title");
const errorEl = document.getElementById("collections-error");
const reloadBtn = document.getElementById("reload-collections");
const form = document.getElementById("job-form");

async function loadCollections() {
  select.disabled = true;
  select.innerHTML = '<option value="">Loading collections…</option>';
  errorEl.hidden = true;
  try {
    const res = await fetch("/api/collections");
    const data = await res.json();
    if (data.error) throw new Error(data.error);
    const cols = data.collections || [];
    if (!cols.length) throw new Error("No collections returned.");
    select.innerHTML = '<option value="">— Select a collection —</option>';
    for (const c of cols) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.dataset.title = c.title;
      const count = c.resources_count != null ? ` (${c.resources_count})` : "";
      opt.textContent = `${c.title}${count}`;
      select.appendChild(opt);
    }
    select.disabled = false;
  } catch (err) {
    select.innerHTML = '<option value="">Failed to load</option>';
    errorEl.textContent = err.message;
    errorEl.hidden = false;
  }
}

select.addEventListener("change", () => {
  const opt = select.selectedOptions[0];
  titleField.value = opt ? opt.dataset.title || "" : "";
});

form.addEventListener("submit", (e) => {
  if (!select.value) {
    e.preventDefault();
    alert("Please choose a collection.");
    return;
  }
  const formats = form.querySelectorAll('input[name="formats"]:checked');
  if (!formats.length) {
    e.preventDefault();
    alert("Choose at least one output format (text and/or PDF).");
  }
});

reloadBtn.addEventListener("click", loadCollections);
loadCollections();
