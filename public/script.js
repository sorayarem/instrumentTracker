"use strict";

const ACCESS_PASSWORD = "listen";
const STORAGE_KEY = "acoustic-tracker-unlocked";

const cells = new Map();
const missionGroups = new Map();
let matrixData = null;
let repoNotes = {};
let selectedCellId = "";
let selectedMissionId = "";

const byId = (id) => document.getElementById(id);

function cellKey(instrumentId, year, month) {
  return `${instrumentId}:${year}:${month}`;
}

function getCellMeta(cellId) {
  const raw = repoNotes[cellId];
  if (raw && typeof raw === "object") {
    return {
      note: raw.note || raw.text || "",
      analysis: raw.analysis || ""
    };
  }
  if (typeof raw === "string") {
    return { note: raw, analysis: "" };
  }
  return { note: "", analysis: "" };
}

function getNote(cellId) {
  return getCellMeta(cellId).note;
}

function getMission(missionId) {
  if (!matrixData?.missions || !missionId) {
    return null;
  }
  return matrixData.missions.find((mission) => mission.id === missionId) || null;
}

function getAnalysisStatus(cellId, cell) {
  const mission = getMission(cell.missionId);
  const { analysis } = getCellMeta(cellId);
  if (analysis) {
    const normalized = analysis.trim().toLowerCase();
    if (normalized.includes("qaqc")) {
      return "qaqc'd";
    }
    if (normalized.includes("listening")) {
      return "not listening";
    }
    if (normalized.includes("not")) {
      return "not analyzed";
    }
    if (normalized.includes("analyzed")) {
      return "analyzed";
    }
    return analysis;
  }
  if (mission?.analysis) {
    return mission.analysis;
  }
  if (cell.display === "listening") {
    return "not listening";
  }
  return cell.status === "available" ? "analyzed" : "not analyzed";
}

function analysisTagClass(status) {
  if (status === "qaqc'd") {
    return "analysis-tag--qaqc";
  }
  if (status === "analyzed") {
    return "analysis-tag--analyzed";
  }
  if (status === "not listening") {
    return "analysis-tag--not-listening";
  }
  return "analysis-tag--not-analyzed";
}

function yearRow(years, year) {
  return years.length - years.indexOf(year);
}

function monthKey(year, month) {
  return `${year}:${month}`;
}

function calendarYearForAcousticMonth(acousticYear, monthName) {
  const startYy = Number.parseInt(acousticYear.split("-")[0], 10);
  const startYear = 2000 + startYy;
  return monthName === "Nov" || monthName === "Dec" ? startYear : startYear + 1;
}

function formatAcousticMonth(acousticYear, monthName) {
  return `${monthName} ${calendarYearForAcousticMonth(acousticYear, monthName)}`;
}

function getListeningInstruments(year, month, excludeInstrumentId) {
  const active = new Set();
  cells.forEach((cell) => {
    if (cell.year !== year || cell.month !== month) {
      return;
    }
    if (cell.instrumentId === excludeInstrumentId) {
      return;
    }
    if (cell.display === "available" || cell.display === "mission") {
      active.add(cell.instrumentName);
    }
  });

  const order = (matrixData?.instruments || []).map(
    (instrument) => instrument.label || instrument.name
  );
  return order.filter((name) => active.has(name));
}

function buildMonthFlags(data) {
  const anyListening = new Set();
  const anyData = new Set();

  data.instruments.forEach((instrument) => {
    instrument.cells.forEach((cell) => {
      const key = monthKey(cell.year, cell.month);
      if (cell.status === "listening") {
        anyListening.add(key);
      }
      if (cell.status === "available") {
        anyData.add(key);
      }
    });
  });

  return { anyListening, anyData };
}

function resolveCellPresentation(cell, instrument, monthFlags) {
  const key = monthKey(cell.year, cell.month);
  const hasData = cell.status === "available";
  const inMission = Boolean(cell.missionId);
  const { anyListening, anyData } = monthFlags;

  if (hasData) {
    const isSoundtrap = instrument.name.startsWith("Soundtrap");
    return {
      visible: true,
      display: "available",
      color: cell.missionColor || instrument.color,
      clickable: isSoundtrap || inMission
    };
  }

  if (inMission) {
    return {
      visible: true,
      display: "mission",
      clickable: true
    };
  }

  const shouldGray = anyData.has(key) || anyListening.has(key);
  if (shouldGray) {
    return {
      visible: true,
      display: "listening",
      clickable: true
    };
  }

  return { visible: false };
}

function missionGroupKey(instrumentId, missionId) {
  return `${instrumentId}:${missionId}`;
}

function isSoundtrapInstrument(instrument) {
  return instrument.name.startsWith("Soundtrap");
}

function soundtrapRowMissionId(year) {
  return `row-${year}`;
}

function resolveIndexedMissionId(instrument, cell, presentation) {
  if (cell.missionId) {
    return cell.missionId;
  }
  if (isSoundtrapInstrument(instrument) && presentation.display === "available") {
    return soundtrapRowMissionId(cell.year);
  }
  return null;
}

const SHARED_MISSION_MONTHS = [
  {
    instrumentId: "glider",
    year: "23-24",
    month: "Feb",
    missionIds: ["glider-winter-23-24-part-i", "glider-winter-23-24-part-ii"]
  },
  {
    instrumentId: "glider",
    year: "24-25",
    month: "Feb",
    missionIds: ["glider-winter-24-25-part-i", "glider-winter-24-25-part-ii"],
    detailMissionId: "glider-winter-24-25-part-ii"
  }
];

function getSharedMonthConfig(instrumentId, year, month) {
  return SHARED_MISSION_MONTHS.find(
    (entry) =>
      entry.instrumentId === instrumentId &&
      entry.year === year &&
      entry.month === month
  );
}

function applySharedMonthDetail(cellRecord) {
  const shared = getSharedMonthConfig(
    cellRecord.instrumentId,
    cellRecord.year,
    cellRecord.month
  );
  if (!shared?.detailMissionId) {
    return;
  }

  const mission = getMission(shared.detailMissionId);
  if (!mission) {
    return;
  }

  cellRecord.missionId = shared.detailMissionId;
  cellRecord.missionLabel = mission.popupMission || mission.label;
  cellRecord.missionDates = mission.popupDates || cellRecord.missionDates;
  cellRecord.missionColor = mission.color || cellRecord.missionColor;
}

function applySharedHighlightGroups() {
  SHARED_MISSION_MONTHS.forEach(({ instrumentId, year, month, missionIds }) => {
    const cellId = cellKey(instrumentId, year, month);

    missionIds.forEach((missionId) => {
      const groupKey = missionGroupKey(instrumentId, missionId);
      if (!missionGroups.has(groupKey)) {
        return;
      }
      missionGroups.get(groupKey).add(cellId);
    });
  });
}

function indexCells(data, monthFlags) {
  cells.clear();
  missionGroups.clear();
  data.instruments.forEach((instrument) => {
    instrument.cells.forEach((cell) => {
      const presentation = resolveCellPresentation(cell, instrument, monthFlags);
      if (!presentation.clickable) {
        return;
      }

      const id = cellKey(instrument.id, cell.year, cell.month);
      const missionId = resolveIndexedMissionId(instrument, cell, presentation);
      const missionColor = cell.missionColor || instrument.color;
      const missionLabel = cell.missionLabel || "";
      const groupedMissionIds = cell.missionIds?.length
        ? cell.missionIds
        : missionId
          ? [missionId]
          : [];

      const cellRecord = {
        id,
        instrumentId: instrument.id,
        instrumentName: instrument.label || instrument.name,
        instrumentColor: instrument.color,
        year: cell.year,
        month: cell.month,
        status: cell.status,
        daysWithData: cell.daysWithData,
        totalDetections: cell.totalDetections,
        missionId,
        missionIds: groupedMissionIds,
        missionLabel,
        missionDates: cell.missionDates || "",
        missionColor,
        display: presentation.display
      };

      applySharedMonthDetail(cellRecord);
      cells.set(id, cellRecord);

      const highlightMissionIds = cellRecord.missionIds.length
        ? cellRecord.missionIds
        : cellRecord.missionId
          ? [cellRecord.missionId]
          : [];

      highlightMissionIds.forEach((groupMissionId) => {
        const groupKey = missionGroupKey(instrument.id, groupMissionId);
        if (!missionGroups.has(groupKey)) {
          missionGroups.set(groupKey, new Set());
        }
        missionGroups.get(groupKey).add(cellRecord.id);
      });
    });
  });

  applySharedHighlightGroups();
}

function renderInstrumentPanels(data, monthFlags) {
  const grid = byId("instrument-grid");
  grid.replaceChildren();

  const bottomRowStart = data.instruments.length - 2;

  data.instruments.forEach((instrument, index) => {
    const displayLabel = instrument.label || instrument.name;
    const isBottomRow = index >= bottomRowStart;

    const panel = document.createElement("article");
    panel.className = isBottomRow ? "panel panel--with-month-axis" : "panel";
    panel.setAttribute("aria-label", displayLabel);
    panel.style.setProperty("--rows", String(data.years.length));

    const panelMain = document.createElement("div");
    panelMain.className = "panel-main";

    const label = document.createElement("h3");
    label.className = "instrument-label";
    label.textContent = displayLabel;
    label.style.color = instrument.color;

    const plot = document.createElement("div");
    plot.className = "plot-area";

    const matrix = document.createElement("div");
    matrix.className = "matrix";

    const yearAxis = document.createElement("div");
    yearAxis.className = "year-axis";
    [...data.years].reverse().forEach((year) => {
      const span = document.createElement("span");
      span.textContent = year;
      yearAxis.append(span);
    });

    instrument.cells.forEach((cell) => {
      const monthIndex = data.months.indexOf(cell.month);
      const row = yearRow(data.years, cell.year);
      const presentation = resolveCellPresentation(cell, instrument, monthFlags);

      if (!presentation.visible) {
        const spacer = document.createElement("span");
        spacer.className = "cell cell--inactive";
        spacer.setAttribute("aria-hidden", "true");
        spacer.style.gridColumn = String(monthIndex + 1);
        spacer.style.gridRow = String(row);
        matrix.append(spacer);
        return;
      }

      const id = cellKey(instrument.id, cell.year, cell.month);
      const node = document.createElement(presentation.clickable ? "button" : "span");
      node.className = "cell";
      if (presentation.clickable) {
        node.type = "button";
        node.dataset.cellId = id;
      } else {
        node.setAttribute("aria-hidden", "true");
      }
      node.dataset.display = presentation.display;
      node.dataset.gridRow = String(row);
      node.dataset.gridCol = String(monthIndex + 1);
      node.style.gridColumn = String(monthIndex + 1);
      node.style.gridRow = String(row);

      if (cell.missionId) {
        node.dataset.missionId = cell.missionId;
        node.dataset.instrumentId = instrument.id;
        const missionColor = cell.missionColor || instrument.color;
        node.style.setProperty("--mission-color", missionColor);
        if (presentation.display === "available" || presentation.display === "mission") {
          node.style.setProperty("--cell-color", missionColor);
        }
      } else if (presentation.display === "available") {
        node.style.setProperty("--cell-color", presentation.color);
      }

      if (presentation.clickable) {
        const missionText = cell.missionLabel ? ` | ${cell.missionLabel}` : "";
        const stateLabel = cell.status === "available" ? "Available" : "Listening";
        const labelText = `${displayLabel}${missionText} | ${formatAcousticMonth(cell.year, cell.month)} | ${stateLabel}`;
        node.title = labelText;
        node.setAttribute("aria-label", labelText);
        node.addEventListener("click", () => selectCell(id));
      }

      matrix.append(node);
    });

    plot.append(matrix, yearAxis);
    panelMain.append(label, plot);

    if (isBottomRow) {
      const monthAxis = document.createElement("div");
      monthAxis.className = "month-axis";
      data.months.forEach((month) => {
        const span = document.createElement("span");
        span.textContent = month;
        monthAxis.append(span);
      });
      panel.append(panelMain, monthAxis);
    } else {
      panel.append(panelMain);
    }

    grid.append(panel);
  });
}

function clearSelectionStyles() {
  document.querySelectorAll(".cell").forEach((node) => {
    node.classList.remove("is-selected");
  });
}

function clearSelection() {
  selectedCellId = "";
  selectedMissionId = "";
  byId("workbench").classList.remove("has-selection");
  byId("right-rail").hidden = true;
  byId("detail-card").replaceChildren();
  clearSelectionStyles();
}

function getSelectedNodes(cell) {
  const groupKey = missionGroupKey(cell.instrumentId, cell.missionId);
  const groupedIds = missionGroups.get(groupKey) || new Set();
  return [...document.querySelectorAll(".cell[data-cell-id]")].filter((node) =>
    groupedIds.has(node.dataset.cellId)
  );
}

function renderDetail(cell) {
  const card = byId("detail-card");
  const mission = getMission(cell.missionId);
  const analysisStatus = getAnalysisStatus(cell.id, cell);
  const note = getNote(cell.id) || mission?.popupNote || "";
  const instrumentColor = cell.missionColor || cell.instrumentColor;

  const noteMarkup = note
    ? `<div class="notes-block"><h3 class="notes-heading">Notes</h3><p class="notes-text">${escapeHtml(note)}</p></div>`
    : "";

  const isGlider = cell.instrumentId === "glider";
  const missionName = mission?.popupMission || cell.missionLabel;
  const missionMarkup =
    isGlider && missionName
      ? `<li><b>Mission</b>${escapeHtml(missionName)}</li>`
      : "";
  const missionDates = mission?.popupDates || cell.missionDates;
  const missionDatesMarkup =
    missionDates
      ? `<li><b>Dates</b>${escapeHtml(missionDates)}</li>`
      : "";

  const r4wLabel = mission?.detailHeading || "R4W MISSION DETAILS";
  const r4wMarkup =
    mission?.r4wUrl
      ? `<p class="r4w-link-line"><a class="r4w-link" href="${escapeHtml(mission.r4wUrl)}" target="_blank" rel="noopener noreferrer" style="color: ${instrumentColor}">${escapeHtml(r4wLabel)}</a></p>`
      : "";

  const listeningInstruments =
    cell.display === "listening"
      ? getListeningInstruments(cell.year, cell.month, cell.instrumentId)
      : [];
  const listeningMarkup =
    listeningInstruments.length > 0
      ? `<div class="listening-block"><h3 class="listening-heading">Listening this month</h3><ul class="listening-list">${listeningInstruments.map((name) => `<li>${escapeHtml(name)}</li>`).join("")}</ul></div>`
      : "";

  card.innerHTML = `
    <span class="analysis-tag ${analysisTagClass(analysisStatus)}">${escapeHtml(analysisStatus)}</span>
    <ul class="detail-list">
      <li><b>Instrument</b>${escapeHtml(cell.instrumentName)}</li>
      ${missionMarkup}
      ${missionDatesMarkup}
    </ul>
    ${listeningMarkup}
    ${r4wMarkup}
    ${noteMarkup}
  `;
}

function escapeHtml(text) {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function applyMissionSelection(cell) {
  clearSelectionStyles();
  const nodes = getSelectedNodes(cell);
  nodes.forEach((node) => node.classList.add("is-selected"));
}

function selectCell(cellId) {
  const cell = cells.get(cellId);
  if (!cell) {
    return;
  }

  if (!cell.missionId) {
    if (selectedCellId === cellId) {
      clearSelection();
      return;
    }

    selectedCellId = cellId;
    selectedMissionId = cellId;
    byId("workbench").classList.add("has-selection");
    byId("right-rail").hidden = false;
    clearSelectionStyles();
    document.querySelectorAll(".cell[data-cell-id]").forEach((node) => {
      node.classList.toggle("is-selected", node.dataset.cellId === cellId);
    });
    renderDetail(cell);
    return;
  }

  const groupKey = missionGroupKey(cell.instrumentId, cell.missionId);
  if (selectedMissionId === groupKey) {
    clearSelection();
    return;
  }

  selectedCellId = cellId;
  selectedMissionId = groupKey;
  byId("workbench").classList.add("has-selection");
  byId("right-rail").hidden = false;
  applyMissionSelection(cell);
  renderDetail(cell);
}

function unlock() {
  byId("gate").classList.add("is-hidden");
  byId("app").hidden = false;
  document.body.classList.add("is-unlocked");
}

function setupGate() {
  if (localStorage.getItem(STORAGE_KEY) === "true") {
    unlock();
    return;
  }

  byId("gate-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const password = byId("password").value.trim();

    if (password === ACCESS_PASSWORD) {
      localStorage.setItem(STORAGE_KEY, "true");
      unlock();
      return;
    }

    byId("gate-error").textContent = "Password did not match.";
    byId("password").select();
  });
}

async function loadJson(path) {
  const url = `${path}${path.includes("?") ? "&" : "?"}t=${Date.now()}`;
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path} (${response.status})`);
  }
  return response.json();
}

async function init() {
  setupGate();

  const logo = document.querySelector(".brand-logo");
  if (logo) {
    logo.src = `assets/whalelogo.png?t=${Date.now()}`;
  }

  try {
    const [matrix, notes] = await Promise.all([
      loadJson("data/matrix.json"),
      loadJson("data/notes.json")
    ]);
    matrixData = matrix;
    repoNotes = notes;
    const monthFlags = buildMonthFlags(matrixData);
    indexCells(matrixData, monthFlags);
    renderInstrumentPanels(matrixData, monthFlags);
    clearSelection();
  } catch (error) {
    byId("instrument-grid").innerHTML = `<p class="load-error">${error.message}</p>`;
  }
}

init();
