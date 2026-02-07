const state = {
  data: null,
  filters: {
    category: new Set(),
    stage: new Set(),
    type: new Set(),
  },
  search: "",
};

const asOfEl = document.getElementById("asOf");
const itemCountEl = document.getElementById("itemCount");
const readoutCountEl = document.getElementById("readoutCount");
const readoutListEl = document.getElementById("readoutList");
const cardGridEl = document.getElementById("cardGrid");
const searchEl = document.getElementById("search");
const categoryFiltersEl = document.getElementById("categoryFilters");
const stageFiltersEl = document.getElementById("stageFilters");
const typeFiltersEl = document.getElementById("typeFilters");
const cardTemplate = document.getElementById("cardTemplate");

const uniq = (arr) => Array.from(new Set(arr)).sort((a, b) => a.localeCompare(b));

const normalize = (value) => value.toLowerCase();

const textIncludes = (haystack, needle) =>
  normalize(haystack).includes(normalize(needle));

function parseDate(dateStr) {
  if (!dateStr) return null;
  const parsed = new Date(dateStr);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function formatDate(dateStr) {
  const date = parseDate(dateStr);
  if (!date) return dateStr || "—";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function buildFilters(items) {
  const categories = uniq(items.map((item) => item.category));
  const stages = uniq(items.map((item) => item.stage));
  const types = uniq(items.map((item) => item.type));

  buildChips(categoryFiltersEl, categories, "category");
  buildChips(stageFiltersEl, stages, "stage");
  buildChips(typeFiltersEl, types, "type");
}

function buildChips(container, values, filterKey) {
  container.innerHTML = "";
  values.forEach((value) => {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.textContent = value;
    chip.addEventListener("click", () => {
      const set = state.filters[filterKey];
      if (set.has(value)) {
        set.delete(value);
        chip.classList.remove("active");
      } else {
        set.add(value);
        chip.classList.add("active");
      }
      renderCards();
    });
    container.appendChild(chip);
  });
}

function getUpcomingReadouts(items) {
  const readouts = [];
  items.forEach((item) => {
    item.trials.forEach((trial) => {
      if (!trial.readout) return;
      readouts.push({
        item: item.name,
        trial: trial.name,
        readout: trial.readout,
        readout_date: trial.readout_date,
      });
    });
  });

  readouts.sort((a, b) => {
    const dateA = parseDate(a.readout_date);
    const dateB = parseDate(b.readout_date);
    if (dateA && dateB) return dateA - dateB;
    if (dateA) return -1;
    if (dateB) return 1;
    return a.readout.localeCompare(b.readout);
  });

  return readouts.slice(0, 6);
}

function renderReadouts(items) {
  const readouts = getUpcomingReadouts(items);
  readoutListEl.innerHTML = "";
  readouts.forEach((entry) => {
    const div = document.createElement("div");
    div.className = "pulse-item";
    div.innerHTML = `<strong>${entry.item}</strong><br/>${entry.trial} — ${entry.readout}`;
    readoutListEl.appendChild(div);
  });
  readoutCountEl.textContent = String(readouts.length);
}

function matchesFilters(item) {
  const { category, stage, type } = state.filters;
  if (category.size && !category.has(item.category)) return false;
  if (stage.size && !stage.has(item.stage)) return false;
  if (type.size && !type.has(item.type)) return false;
  if (!state.search) return true;

  const haystack = [
    item.name,
    item.company,
    item.mechanism,
    item.focus,
    item.category,
    item.stage,
    item.type,
    item.latest_update,
    item.notes,
    ...item.tags,
    ...item.trials.map((trial) => `${trial.name} ${trial.status} ${trial.readout || ""}`),
  ].join(" ");

  return textIncludes(haystack, state.search);
}

function buildCard(item) {
  const node = cardTemplate.content.cloneNode(true);
  const card = node.querySelector(".card");
  const title = node.querySelector(".card-title");
  const sub = node.querySelector(".card-sub");
  const pill = node.querySelector(".pill");
  const mechanism = node.querySelector(".mechanism");
  const focus = node.querySelector(".focus");
  const latest = node.querySelector(".latest");
  const trials = node.querySelector(".trials");
  const tags = node.querySelector(".tags");
  const company = node.querySelector(".company");
  const drawer = node.querySelector(".drawer");
  const drawerContent = node.querySelector(".drawer-content");
  const details = node.querySelector(".details");

  title.textContent = item.name;
  sub.textContent = item.category;
  pill.textContent = item.stage;
  mechanism.textContent = item.mechanism;
  focus.textContent = item.focus;
  latest.textContent = item.latest_update;
  trials.textContent = item.trials.map((trial) => trial.name).join(", ");
  company.textContent = item.company;

  item.tags.forEach((tag) => {
    const span = document.createElement("span");
    span.className = "tag";
    span.textContent = tag;
    tags.appendChild(span);
  });

  drawerContent.innerHTML = `
    <strong>Trials:</strong>
    <ul>
      ${item.trials
        .map(
          (trial) =>
            `<li><strong>${trial.name}</strong> (${trial.phase}) — ${trial.status}. Readout: ${trial.readout || "TBD"} ${
              trial.registry_id ? `· ${trial.registry_id}` : ""
            }</li>`
        )
        .join("")}
    </ul>
    <strong>Notes:</strong>
    <p>${item.notes}</p>
  `;

  details.addEventListener("click", () => {
    drawer.classList.toggle("open");
    details.textContent = drawer.classList.contains("open") ? "Close" : "Details";
  });

  return node;
}

function renderCards() {
  const items = state.data.items.filter(matchesFilters);
  cardGridEl.innerHTML = "";
  items.forEach((item) => cardGridEl.appendChild(buildCard(item)));
  itemCountEl.textContent = String(items.length);
}

async function init() {
  const response = await fetch("data/afib.json");
  const data = await response.json();
  state.data = data;

  asOfEl.textContent = formatDate(data.as_of);
  buildFilters(data.items);
  renderReadouts(data.items);
  renderCards();

  searchEl.addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    renderCards();
  });
}

init();
