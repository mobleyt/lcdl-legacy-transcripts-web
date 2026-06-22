// Stream live progress for this job via Server-Sent Events.
const logEl = document.getElementById("log");
const statusEl = document.getElementById("status");
const spinner = document.getElementById("spinner");
const actions = document.getElementById("actions");
const downloadLink = document.getElementById("download");

function append(line) {
  logEl.textContent += line + "\n";
  logEl.scrollTop = logEl.scrollHeight;
}

function finish(state) {
  spinner.classList.add("hidden");
  if (state === "error") {
    statusEl.classList.add("error");
  } else {
    actions.hidden = false;
    downloadLink.hidden = false;
  }
}

const source = new EventSource(`/jobs/${window.JOB_ID}/events`);

source.onmessage = (e) => {
  const ev = JSON.parse(e.data);
  switch (ev.type) {
    case "status":
      statusEl.textContent = ev.message;
      append("» " + ev.message);
      break;
    case "log":
      if (ev.message.trim()) append(ev.message);
      break;
    case "done":
      statusEl.textContent = "Done.";
      append("✓ " + ev.message);
      finish("done");
      source.close();
      break;
    case "error":
      statusEl.textContent = ev.message;
      append("✗ " + ev.message);
      finish("error");
      source.close();
      break;
    case "end":
      source.close();
      break;
  }
};

source.onerror = () => {
  // Connection dropped; the browser will retry automatically unless closed.
  append("… connection interrupted, retrying");
};
