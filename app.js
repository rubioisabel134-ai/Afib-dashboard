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
const viewAllDevicesBtn = document.getElementById("viewAllDevices");
const viewAllDrugsBtn = document.getElementById("viewAllDrugs");
const cardGridEl = document.getElementById("cardGrid");
const searchEl = document.getElementById("search");
const categoryFiltersEl = document.getElementById("categoryFilters");
const stageFiltersEl = document.getElementById("stageFilters");
const typeFiltersEl = document.getElementById("typeFilters");
const weeklySafetyLabelEl = document.getElementById("weeklySafetyLabel");
const weeklyConferenceEl = document.getElementById("weeklyConference");
const weeklyPressEl = document.getElementById("weeklyPress");
const conferenceFeedEl = document.getElementById("conferenceFeed");
const conferenceCalendarEl = document.getElementById("conferenceCalendar");
const conferenceStatusEl = document.getElementById("conferenceStatus");
const cardTemplate = document.getElementById("cardTemplate");
const WEEKLY_PREVIEW_LIMIT = 5;
const SUMMARY_UPDATE_LIMIT = 4;

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
      company: item.company || "Unknown",
      date: extractUpdateDate(item.latest_update || ""),
      source: bestUpdateSource(item),
    }))
    .sort((a, b) => {
      if (a.press !== b.press) return a.press ? -1 : 1;
      if ((b.date || "") !== (a.date || "")) return (b.date || "").localeCompare(a.date || "");
      return stagePriority(a.stage) - stagePriority(b.stage);
    })
    .slice(0, SUMMARY_UPDATE_LIMIT);
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
    const node = document.createElement(entry.source ? "a" : "div");
    node.className = "pulse-item";
    if (entry.source) {
      node.href = entry.source;
      node.target = "_blank";
      node.rel = "noopener noreferrer";
    }
    const badges = buildUpdateBadges(entry);
    node.innerHTML = `<strong>${entry.name}</strong>
      <div class="pulse-meta">${entry.date || "Date TBD"} · ${entry.company}</div>
      <div class="pulse-update">${entry.update}</div>
      <div class="pulse-badges">${badges.map((badge) => `<span class="pulse-tag">${badge}</span>`).join("")}</div>`;
    container.appendChild(node);
  });
}

function extractUpdateDate(updateText) {
  const m = (updateText || "").match(/^(\d{4}-\d{2}-\d{2})[:\s]/);
  return m ? m[1] : "";
}

function bestUpdateSource(item) {
  if (item?.latest_update_link) {
    return item.latest_update_link;
  }
  const updateText = item?.latest_update || "";
  const nctMatch = updateText.match(/\bNCT\d{8}\b/i);
  if (nctMatch) {
    return `https://clinicaltrials.gov/study/${nctMatch[0].toUpperCase()}`;
  }
  if (/clinicaltrials\.gov|trial|phase|recruiting|enrollment/i.test(updateText)) {
    const trialWithRegistry = (item?.trials || []).find((trial) => (trial?.registry_id || "").match(/^NCT\d{8}$/i));
    if (trialWithRegistry) {
      return `https://clinicaltrials.gov/study/${trialWithRegistry.registry_id.toUpperCase()}`;
    }
  }
  const sources = item?.sources || [];
  if (!sources.length) return "";
  return sources[sources.length - 1] || "";
}

function buildUpdateBadges(entry) {
  const badges = [];
  const text = `${entry.update || ""} ${entry.stage || ""}`.toLowerCase();
  if (entry.press) badges.push("Press");
  if (
    text.includes("approval") ||
    text.includes("approved") ||
    text.includes("fda") ||
    text.includes("ce mark") ||
    text.includes("nmpa") ||
    text.includes("pmda") ||
    text.includes("patent")
  ) {
    badges.push("Regulatory");
  }
  if (
    text.includes("phase") ||
    text.includes("trial") ||
    text.includes("nct") ||
    text.includes("enrollment") ||
    text.includes("recruiting")
  ) {
    badges.push("Trial");
  }
  if (text.includes("readout") || text.includes("topline") || text.includes("results")) {
    badges.push("Readout");
  }
  if (!badges.length) badges.push("Update");
  return badges.slice(0, 3);
}

function setTypeFilter(type) {
  state.filters.type.clear();
  state.filters.type.add(type);
  Array.from(typeFiltersEl.querySelectorAll(".chip")).forEach((chip) => {
    chip.classList.toggle("active", chip.textContent === type);
  });
  renderCards();
  cardGridEl.scrollIntoView({ behavior: "smooth", block: "start" });
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
  const latestSource = bestUpdateSource(item);

  title.textContent = item.name;
  sub.textContent = item.category;
  pill.textContent = item.stage;
  mechanism.textContent = item.mechanism;
  focus.textContent = item.focus;
  if (latestSource) {
    latest.innerHTML = "";
    const latestLink = document.createElement("a");
    latestLink.href = latestSource;
    latestLink.target = "_blank";
    latestLink.rel = "noopener noreferrer";
    latestLink.textContent = item.latest_update;
    latest.appendChild(latestLink);
  } else {
    latest.textContent = item.latest_update;
  }
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
  const sourceLinks = (item.sources || [])
    .map((source) => `<li><a href="${source}" target="_blank" rel="noopener noreferrer">${source}</a></li>`)
    .join("");
  if (sourceLinks) {
    drawerContent.innerHTML += `
      <strong>Sources:</strong>
      <ul>${sourceLinks}</ul>
    `;
  }

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

function parseCalendarDate(dateStr) {
  if (!dateStr) return null;
  const parsed = new Date(`${dateStr}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed;
}

function formatCalendarRange(start, end) {
  const startDate = parseCalendarDate(start);
  const endDate = parseCalendarDate(end);
  if (!startDate || !endDate) return `${start || "TBD"} to ${end || "TBD"}`;
  const startLabel = startDate.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const endLabel = endDate.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
  return `${startLabel} to ${endLabel}`;
}

function conferenceState(calendarEntries) {
  const now = new Date();
  const active = calendarEntries.find((entry) => {
    const start = parseCalendarDate(entry.start_date);
    const end = parseCalendarDate(entry.end_date);
    return start && end && start <= now && now <= end;
  });
  const upcoming = calendarEntries
    .filter((entry) => {
      const start = parseCalendarDate(entry.start_date);
      return start && start >= new Date(now.getFullYear(), now.getMonth(), now.getDate());
    })
    .sort((a, b) => (a.start_date || "").localeCompare(b.start_date || ""));
  return { active, upcoming };
}

function renderConferenceCalendar(calendarEntries, weeklyConference) {
  if (!conferenceCalendarEl || !conferenceStatusEl || !conferenceFeedEl) return;

  const { active, upcoming } = conferenceState(calendarEntries || []);
  if (active) {
    conferenceStatusEl.textContent = `Active Meeting: ${active.label || active.conference}`;
  } else if (upcoming.length) {
    conferenceStatusEl.textContent = `Next Meeting: ${upcoming[0].label || upcoming[0].conference}`;
  } else {
    conferenceStatusEl.textContent = "No conference windows loaded";
  }

  conferenceCalendarEl.innerHTML = "";
  const calendarPreview = (active ? [active, ...upcoming.filter((entry) => entry !== active)] : upcoming).slice(0, 4);
  if (!calendarPreview.length) {
    const empty = document.createElement("div");
    empty.className = "conference-meeting";
    empty.textContent = "No upcoming conferences loaded.";
    conferenceCalendarEl.appendChild(empty);
  } else {
    calendarPreview.forEach((entry) => {
      const node = document.createElement("div");
      node.className = "conference-meeting";
      node.innerHTML = `<strong>${entry.label || entry.conference}</strong><div class="conference-meta">${formatCalendarRange(
        entry.start_date,
        entry.end_date,
      )}</div><div class="conference-meta">${entry.conference}</div>`;
      conferenceCalendarEl.appendChild(node);
    });
  }

  const activeCode = (active?.conference || "").toLowerCase();
  const prioritizedConference = [...(weeklyConference || [])].sort((a, b) => {
    const aHit = activeCode && `${a.title || ""} ${a.source || ""}`.toLowerCase().includes(activeCode) ? 1 : 0;
    const bHit = activeCode && `${b.title || ""} ${b.source || ""}`.toLowerCase().includes(activeCode) ? 1 : 0;
    if (bHit !== aHit) return bHit - aHit;
    return (b.date || "").localeCompare(a.date || "");
  });
  renderWeeklyList(conferenceFeedEl, prioritizedConference.slice(0, 8));
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

  const scored = entries
    .map((entry, idx) => ({
      ...entry,
      _idx: idx,
      _asset: extractAssetKey(entry),
      _date: parseDate(entry.date),
      _score: weeklyPriority(entry),
      _sourceRank: weeklySourceRank(entry.source || ""),
    }))
    .sort((a, b) => {
      if (b._score !== a._score) return b._score - a._score;
      if ((b._date?.getTime() || 0) !== (a._date?.getTime() || 0)) return (b._date?.getTime() || 0) - (a._date?.getTime() || 0);
      if (a._sourceRank !== b._sourceRank) return a._sourceRank - b._sourceRank;
      return a._idx - b._idx;
    });

  const preview = [];
  const previewAssetSeen = new Set();
  for (const entry of scored) {
    if (preview.length >= WEEKLY_PREVIEW_LIMIT) break;
    if (entry._asset && previewAssetSeen.has(entry._asset)) continue;
    preview.push(entry);
    if (entry._asset) previewAssetSeen.add(entry._asset);
  }

  const previewIdx = new Set(preview.map((e) => e._idx));
  const extra = scored.filter((e) => !previewIdx.has(e._idx));

  preview.forEach((entry) => {
    const div = document.createElement(entry.link ? "a" : "div");
    div.className = "weekly-item";
    if (entry.link) {
      div.href = entry.link;
      div.target = "_blank";
      div.rel = "noopener noreferrer";
    }
    div.innerHTML = `<strong>${entry.title}</strong><span>${entry.date || "Date TBD"} · ${
      entry.source || "Source TBD"
    }</span>`;
    container.appendChild(div);
  });

  if (extra.length) {
    const extraWrap = document.createElement("div");
    extraWrap.className = "weekly-extra";
    extraWrap.hidden = true;

    extra.forEach((entry) => {
      const div = document.createElement(entry.link ? "a" : "div");
      div.className = "weekly-item";
      if (entry.link) {
        div.href = entry.link;
        div.target = "_blank";
        div.rel = "noopener noreferrer";
      }
      div.innerHTML = `<strong>${entry.title}</strong><span>${entry.date || "Date TBD"} · ${
        entry.source || "Source TBD"
      }</span>`;
      extraWrap.appendChild(div);
    });
    container.appendChild(extraWrap);

    const toggle = document.createElement("button");
    toggle.className = "weekly-toggle";
    toggle.type = "button";
    toggle.textContent = `Show ${extra.length} more`;
    toggle.addEventListener("click", () => {
      const open = !extraWrap.hidden;
      extraWrap.hidden = open;
      toggle.textContent = open ? `Show ${extra.length} more` : "Show less";
    });
    container.appendChild(toggle);
  }
}

function extractAssetKey(entry) {
  const source = (entry?.source || "").toLowerCase();
  const m = source.match(/match:\s*(.+)$/i);
  if (!m) return "";
  return m[1].trim();
}

function weeklySourceRank(source) {
  const s = (source || "").toLowerCase();
  if (s.includes("press release") || s.includes("press releases") || s.includes("mediaroom")) return 1;
  if (s.includes("fda") || s.includes("ema")) return 2;
  if (s.includes("google news")) return 4;
  return 3;
}

function weeklyPriority(entry) {
  const title = (entry?.title || "").toLowerCase();
  const source = (entry?.source || "").toLowerCase();
  const text = `${title} ${source}`;
  let score = 0;

  if (
    text.includes("fda") ||
    text.includes("ema") ||
    text.includes("ce mark") ||
    text.includes("nmpa") ||
    text.includes("pmda") ||
    text.includes("approval") ||
    text.includes("approved") ||
    text.includes("clearance") ||
    text.includes("patent")
  ) {
    score += 5;
  }

  if (source.includes("press release") || source.includes("press releases") || source.includes("mediaroom")) {
    score += 4;
  }

  if (
    text.includes("phase 3") ||
    text.includes("phase iii") ||
    text.includes("phase 2") ||
    text.includes("phase ii") ||
    text.includes("pivotal") ||
    text.includes("topline") ||
    text.includes("enrollment complete")
  ) {
    score += 3;
  }

  if (text.includes("nct")) score += 2;

  if (
    text.includes("stock price") ||
    text.includes("insider buy") ||
    text.includes("marketbeat") ||
    text.includes("yahoo finance")
  ) {
    score -= 3;
  }

  if (text.includes("obituary") || text.includes("funeral")) score -= 5;
  return score;
}

function renderWeeklyIntel(weekly) {
  if (!weekly) return;
  const mergedSafetyLabel = [
    ...(weekly.safety_signals || []),
    ...(weekly.label_expansions || []),
    ...(weekly.guideline_updates || []),
  ].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  renderWeeklyList(weeklySafetyLabelEl, mergedSafetyLabel);
  renderWeeklyList(weeklyConferenceEl, weekly.conference_abstracts);
  renderWeeklyList(weeklyPressEl, weekly.press_pipeline);
}

async function init() {
  const [dataResponse, calendarResponse] = await Promise.all([
    fetch("data/afib.json"),
    fetch("data/conference_calendar.json").catch(() => null),
  ]);
  const data = await dataResponse.json();
  let conferenceCalendar = [];
  if (calendarResponse && calendarResponse.ok) {
    conferenceCalendar = await calendarResponse.json();
  }
  state.data = data;

  asOfEl.textContent = formatDate(data.as_of);
  buildFilters(data.items);
  const deviceUpdates = buildUpdateEntries(data.items.filter((item) => item.type === "Device"));
  const drugUpdates = buildUpdateEntries(data.items.filter((item) => item.type === "Drug"));
  renderUpdateList(deviceUpdateListEl, deviceUpdates);
  renderUpdateList(drugUpdateListEl, drugUpdates);
  readoutCountEl.textContent = String(deviceUpdates.length + drugUpdates.length);
  renderWeeklyIntel(data.weekly_updates);
  renderConferenceCalendar(conferenceCalendar, data.weekly_updates?.conference_abstracts || []);
  renderCards();

  searchEl.addEventListener("input", (event) => {
    state.search = event.target.value.trim();
    renderCards();
  });
  if (viewAllDevicesBtn) viewAllDevicesBtn.addEventListener("click", () => setTypeFilter("Device"));
  if (viewAllDrugsBtn) viewAllDrugsBtn.addEventListener("click", () => setTypeFilter("Drug"));
}

init();
