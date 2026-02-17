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
const deviceUpdateListEl = document.getElementById("deviceUpdateList");
const drugUpdateListEl = document.getElementById("drugUpdateList");
const cardGridEl = document.getElementById("cardGrid");
const searchEl = document.getElementById("search");
const categoryFiltersEl = document.getElementById("categoryFilters");
const stageFiltersEl = document.getElementById("stageFilters");
const typeFiltersEl = document.getElementById("typeFilters");
const weeklySafetyEl = document.getElementById("weeklySafety");
const weeklyLabelEl = document.getElementById("weeklyLabel");
const weeklyGuidelineEl = document.getElementById("weeklyGuideline");
const weeklyConferenceEl = document.getElementById("weeklyConference");
const weeklyPressEl = document.getElementById("weeklyPress");
const cardTemplate = document.getElementById("cardTemplate");

const uniq = (arr) => Array.from(new Set(arr)).sort((a, b) => a.localeCompare(b));

const CATEGORY_ORDER = [
  "Rate Control",
  "Rhythm Control",
  "PFA Ablation",
  "Thermal Ablation",
  "Stroke Prevention",
];

const STAGE_ORDER = [
  "Preclinical",
  "Phase I",
  "Phase II",
  "Phase III",
  "Pivotal",
  "Approved",
  "Pre-registered",
];

function mapCategory(item) {
  const category = (item.category || "").toLowerCase();
  if (category.includes("rate control")) return "Rate Control";
  if (category.includes("rhythm control") || category.includes("antiarrhythmic")) return "Rhythm Control";
  if (category.includes("pfa")) return "PFA Ablation";
  if (category.includes("rf") || category.includes("cryo") || category.includes("thermal")) return "Thermal Ablation";
  if (
    category.includes("stroke prevention") ||
    category.includes("anticoagulant") ||
    category.includes("fxi") ||
    category.includes("laa")
  )
    return "Stroke Prevention";
  return null;
}

function mapStage(item) {
  const stage = (item.stage || "").toLowerCase();
  if (stage.includes("preclinical") || stage.includes("ind")) return "Preclinical";
  if (stage.includes("phase 1") || stage.includes("phase i")) return "Phase I";
  if (stage.includes("phase 2") || stage.includes("phase ii")) return "Phase II";
  if (stage.includes("phase 3") || stage.includes("phase iii")) return "Phase III";
  if (stage.includes("pivotal")) return "Pivotal";
  if (stage.includes("approved") || stage.includes("fda") || stage.includes("ce mark") || stage.includes("nmpa"))
    return "Approved";
  if (stage.includes("pre-registered") || stage.includes("planned") || stage.includes("ide")) return "Pre-registered";
  return null;
}

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
  const categories = uniq(items.map(mapCategory).filter(Boolean));
  const stages = uniq(items.map(mapStage).filter(Boolean));
  const types = uniq(items.map((item) => item.type));

  buildChips(categoryFiltersEl, categories, "category", CATEGORY_ORDER);
  buildChips(stageFiltersEl, stages, "stage", STAGE_ORDER);
  buildChips(typeFiltersEl, types, "type");
}

function buildChips(container, values, filterKey, preferredOrder = null) {
  container.innerHTML = "";
  const orderedValues = preferredOrder
    ? preferredOrder.filter((value) => values.includes(value))
    : values;
  orderedValues.forEach((value) => {
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

function has2026Update(item) {
  if (item.bubble_exclude) return false;
  if (item.latest_update && item.latest_update.includes("2026")) return true;
  return item.trials.some((trial) => {
    if (trial.readout && trial.readout.includes("2026")) return true;
    return trial.readout_date ? new Date(trial.readout_date).getFullYear() === 2026 : false;
  });
}

function stagePriority(stage) {
  const value = (stage || "").toLowerCase();
  if (value.includes("phase 3") || value.includes("phase iii")) return 1;
  if (value.includes("phase 2") || value.includes("phase ii")) return 2;
  if (value.includes("phase 1") || value.includes("phase i")) return 3;
  if (value.includes("pivotal")) return 4;
  if (value.includes("preclinical")) return 5;
  if (value.includes("approved") || value.includes("fda") || value.includes("ce mark")) return 9;
  return 6;
}

function buildUpdateEntries(items) {
  return items
    .filter((item) => !(item.type === "Drug" && /generic/i.test(item.company || "")))
    .filter(has2026Update)
    .map((item) => ({
      name: item.name,
      update: item.latest_update || "2026 update noted in trials",
      type: item.type,
      press: Boolean(item.press_2026),
      stage: item.stage || "",
    }))
    .sort((a, b) => {
      if (a.press !== b.press) return a.press ? -1 : 1;
      return stagePriority(a.stage) - stagePriority(b.stage);
    })
    .slice(0, 6);
}

function renderUpdateList(container, entries) {
  container.innerHTML = "";
  if (!entries.length) {
    const div = document.createElement("div");
    div.className = "pulse-item";
    div.textContent = "No 2026 updates found.";
    container.appendChild(div);
    return;
  }
  entries.forEach((entry) => {
    const div = document.createElement("div");
    div.className = "pulse-item";
    div.innerHTML = `<strong>${entry.name}</strong><br/>${entry.update}${
      entry.press ? '<div class="pulse-tag">Press Release</div>' : ""
    }`;
    container.appendChild(div);
  });
}

function matchesFilters(item) {
  const { category, stage, type } = state.filters;
  const mappedCategory = mapCategory(item);
  const mappedStage = mapStage(item);
  if (category.size && !category.has(mappedCategory)) return false;
  if (stage.size && !stage.has(mappedStage)) return false;
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

function renderWeeklyList(container, entries) {
  container.innerHTML = "";
  if (!entries || !entries.length) {
    const div = document.createElement("div");
    div.className = "weekly-item";
    div.textContent = "No updates logged.";
    container.appendChild(div);
    return;
  }
  entries.forEach((entry) => {
    const div = document.createElement("div");
    div.className = "weekly-item";
    div.innerHTML = `<strong>${entry.title}</strong><span>${entry.date || "Date TBD"} · ${
      entry.source || "Source TBD"
    }</span>`;
    container.appendChild(div);
  });
}

function renderWeeklyIntel(weekly) {
  if (!weekly) return;
  renderWeeklyList(weeklySafetyEl, weekly.safety_signals);
  renderWeeklyList(weeklyLabelEl, weekly.label_expansions);
  renderWeeklyList(weeklyGuidelineEl, weekly.guideline_updates);
  renderWeeklyList(weeklyConferenceEl, weekly.conference_abstracts);
  renderWeeklyList(weeklyPressEl, weekly.press_pipeline);
}

async function init() {
  const response = await fetch("data/afib.json");
  const data = await response.json();
  state.data = data;

  asOfEl.textContent = formatDate(data.as_of);
  buildFilters(data.items);
  const deviceUpdates = buildUpdateEntries(data.items.filter((item) => item.type === "Device"));
  const drugUpdates = buildUpdateEntries(data.items.filter((item) => item.type === "Drug"));
  renderUpdateList(deviceUpdateListEl, deviceUpdates);
  renderUpdateList(drugUpdateListEl, drugUpdates);
  readoutCountEl.textContent = String(deviceUpdates.length + drugUpdates.length);
  renderWeeklyIntel(data.weekly_updates);
  renderCards();

  searchEl.addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    renderCards();
  });
}

init();
