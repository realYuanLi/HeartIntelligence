/*********************************************************************
 *  calendar.js — Workout Calendar UI
 *
 *  The calendar grid is always visible. When a workout plan exists
 *  (created via chat), scheduled days are "filled in" with labels,
 *  exercise previews, and completion state.
 *
 *  Below the month grid, a week-by-week strip shows the concrete
 *  schedule for a selected week. Clicking a day in the month grid
 *  selects that week. The "today" panel shows exercises for the
 *  selected day, with one-click delete buttons on each exercise.
 *********************************************************************/

(function () {
  "use strict";

  let currentYear, currentMonth; // 1-indexed month
  let activePlan = null;
  let monthDays  = [];           // cached from last API fetch

  // Week strip state
  let selectedDate = null;       // YYYY-MM-DD — the day selected in the grid
  let weekOffset   = 0;          // 0 = week containing selectedDate, -1 = prev, +1 = next

  const MONTH_NAMES = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
  ];
  const DAY_NAMES_ORDER = [
    "monday","tuesday","wednesday","thursday","friday","saturday","sunday"
  ];
  const DAY_SHORT = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"];

  /* ---- DOM refs ---- */
  const calCells       = document.getElementById("calCells");
  const calMonthLabel  = document.getElementById("calMonthLabel");
  const calPrev        = document.getElementById("calPrev");
  const calNext        = document.getElementById("calNext");
  const todayPanel     = document.getElementById("todayPanel");
  const todayLabel     = document.getElementById("todayLabel");
  const todayExercises = document.getElementById("todayExercises");
  const todayCompleteBtn = document.getElementById("todayCompleteBtn");
  const exportIcalBtn  = document.getElementById("exportIcalBtn");
  const planStrip      = document.getElementById("planStrip");
  const planTitle      = document.getElementById("planTitle");
  const weekStrip      = document.getElementById("weekStrip");
  const weekLabel      = document.getElementById("weekLabel");
  const weekDays       = document.getElementById("weekDays");
  const weekPrev       = document.getElementById("weekPrev");
  const weekNext       = document.getElementById("weekNext");

  /* ---- Init ---- */
  const now = new Date();
  currentYear  = now.getFullYear();
  currentMonth = now.getMonth() + 1;
  selectedDate = localTodayStr();

  calPrev.addEventListener("click", () => changeMonth(-1));
  calNext.addEventListener("click", () => changeMonth(1));

  if (weekPrev) weekPrev.addEventListener("click", () => { weekOffset--; renderWeekStrip(); renderDayPanel(); });
  if (weekNext) weekNext.addEventListener("click", () => { weekOffset++; renderWeekStrip(); renderDayPanel(); });

  if (exportIcalBtn) {
    exportIcalBtn.addEventListener("click", () => {
      window.location.href = "/api/workout-plan/export-ical";
    });
  }

  if (todayCompleteBtn) {
    todayCompleteBtn.addEventListener("click", () => {
      const dateStr = getSelectedWeekDay();
      toggleComplete(dateStr, true);
    });
  }

  // Initial load
  loadPlanThenRender();

  // Auto-poll every 5 seconds so chat-driven changes appear quickly.
  let lastPlanJSON = "";
  let pollTimer = setInterval(pollForChanges, 5000);

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearInterval(pollTimer);
      pollTimer = null;
    } else {
      pollForChanges();
      pollTimer = setInterval(pollForChanges, 5000);
    }
  });

  function pollForChanges() {
    fetch("/api/workout-plan")
      .then(r => r.json())
      .then(data => {
        const plan = (data.success && data.plan) ? data.plan : null;
        const json = JSON.stringify(plan);
        if (json !== lastPlanJSON) {
          lastPlanJSON = json;
          activePlan = plan;
          updatePlanStrip();
          renderMonth();
          renderWeekStrip();
          renderDayPanel();
        }
      })
      .catch(() => {});
  }

  /* ================================================================ */
  /*  Data loading                                                     */
  /* ================================================================ */

  function loadPlanThenRender() {
    fetch("/api/workout-plan")
      .then(r => r.json())
      .then(data => {
        activePlan = (data.success && data.plan) ? data.plan : null;
        lastPlanJSON = JSON.stringify(activePlan);
        updatePlanStrip();
        renderMonth();
        renderWeekStrip();
        renderDayPanel();
      })
      .catch(() => {
        activePlan = null;
        lastPlanJSON = "";
        updatePlanStrip();
        renderMonth();
      });
  }

  function updatePlanStrip() {
    if (activePlan) {
      planStrip.hidden = false;
      planTitle.textContent = activePlan.title || "Workout Plan";
      exportIcalBtn.hidden = false;
    } else {
      planStrip.hidden = true;
      exportIcalBtn.hidden = true;
    }
  }

  /* ================================================================ */
  /*  Month navigation                                                 */
  /* ================================================================ */

  function changeMonth(delta) {
    currentMonth += delta;
    if (currentMonth < 1)  { currentMonth = 12; currentYear--; }
    if (currentMonth > 12) { currentMonth = 1;  currentYear++; }
    renderMonth();
  }

  /* ================================================================ */
  /*  Build the month grid                                             */
  /* ================================================================ */

  function renderMonth() {
    calMonthLabel.textContent = `${MONTH_NAMES[currentMonth - 1]} ${currentYear}`;

    fetch(`/api/workout-plan/calendar?year=${currentYear}&month=${currentMonth}`)
      .then(r => r.json())
      .then(data => {
        monthDays = data.success ? (data.days || []) : [];
        buildGrid(monthDays);
      })
      .catch(() => {
        monthDays = buildPlainDays(currentYear, currentMonth);
        buildGrid(monthDays);
      });
  }

  function buildPlainDays(year, month) {
    const days = [];
    const count = new Date(year, month, 0).getDate();
    const dayNames = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"];
    for (let d = 1; d <= count; d++) {
      const dateObj = new Date(year, month - 1, d);
      const wd = dateObj.getDay();
      days.push({
        date: dateObj.toISOString().slice(0, 10),
        weekday: dayNames[wd === 0 ? 6 : wd - 1],
        has_workout: false,
        completed: false,
      });
    }
    return days;
  }

  function buildGrid(days) {
    calCells.innerHTML = "";
    if (!days.length) return;

    const firstDate = new Date(days[0].date + "T00:00:00");
    let startOffset = firstDate.getDay() - 1;
    if (startOffset < 0) startOffset = 6;

    for (let i = 0; i < startOffset; i++) {
      calCells.appendChild(makeBlankCell());
    }

    const todayStr = localTodayStr();

    days.forEach(day => {
      const cell = document.createElement("div");
      cell.className = "cal-cell";

      const isToday = day.date === todayStr;
      const isSelected = day.date === selectedDate;
      if (isToday)          cell.classList.add("today");
      if (day.has_workout)  cell.classList.add("has-workout");
      if (day.completed)    cell.classList.add("completed");
      if (isSelected)       cell.classList.add("selected");

      const num = document.createElement("span");
      num.className = "cal-date-num";
      num.textContent = new Date(day.date + "T00:00:00").getDate();
      cell.appendChild(num);

      if (day.has_workout) {
        const label = document.createElement("div");
        label.className = "cal-workout-label";
        label.textContent = day.label || "";
        cell.appendChild(label);

        const count = document.createElement("div");
        count.className = "cal-exercise-count";
        count.textContent = day.exercise_count ? `${day.exercise_count} exercises` : "";
        cell.appendChild(count);
      }

      if (day.completed) {
        const badge = document.createElement("span");
        badge.className = "cal-check-badge";
        badge.innerHTML = `<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>`;
        cell.appendChild(badge);
      }

      // Click selects this day and shows its week
      cell.addEventListener("click", () => {
        selectedDate = day.date;
        weekOffset = 0;
        renderMonth(); // re-render to update selection highlight
        renderWeekStrip();
        renderDayPanel();
      });

      calCells.appendChild(cell);
    });

    const totalCells = startOffset + days.length;
    const trailing = (7 - (totalCells % 7)) % 7;
    for (let i = 0; i < trailing; i++) {
      calCells.appendChild(makeBlankCell());
    }
  }

  function makeBlankCell() {
    const el = document.createElement("div");
    el.className = "cal-cell blank";
    return el;
  }

  function localTodayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  }

  /* ================================================================ */
  /*  Week strip — shows a concrete week with day-by-day breakdown     */
  /* ================================================================ */

  function getWeekDates() {
    // Get Monday of the week containing selectedDate, shifted by weekOffset
    const base = new Date(selectedDate + "T00:00:00");
    let dayOfWeek = base.getDay(); // 0=Sun
    if (dayOfWeek === 0) dayOfWeek = 7;
    const monday = new Date(base);
    monday.setDate(base.getDate() - (dayOfWeek - 1) + (weekOffset * 7));

    const dates = [];
    for (let i = 0; i < 7; i++) {
      const d = new Date(monday);
      d.setDate(monday.getDate() + i);
      dates.push(d);
    }
    return dates;
  }

  function getSelectedWeekDay() {
    // Return the date string of the currently selected day in the active week
    const dates = getWeekDates();
    // Find which date in this week matches selectedDate; default to first
    const sel = selectedDate;
    for (const d of dates) {
      if (formatDate(d) === sel) return sel;
    }
    return formatDate(dates[0]);
  }

  function formatDate(d) {
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}`;
  }

  function renderWeekStrip() {
    if (!activePlan || !activePlan.schedule) {
      weekStrip.hidden = true;
      return;
    }

    weekStrip.hidden = false;
    const dates = getWeekDates();
    const schedule = activePlan.schedule || {};
    const completions = activePlan.completions || {};
    const todayStr = localTodayStr();

    // Week label
    const mon = dates[0];
    const sun = dates[6];
    weekLabel.textContent = `${formatShortDate(mon)} — ${formatShortDate(sun)}`;

    weekDays.innerHTML = "";
    dates.forEach((d, i) => {
      const dateStr = formatDate(d);
      const dayName = DAY_NAMES_ORDER[i];
      const daySchedule = schedule[dayName];
      const isCompleted = completions[dateStr] && completions[dateStr].completed;
      const isToday = dateStr === todayStr;
      const isSelected = dateStr === selectedDate;
      const isPast = dateStr < todayStr;

      const el = document.createElement("div");
      el.className = "week-day-cell";
      if (isToday) el.classList.add("today");
      if (isSelected) el.classList.add("selected");
      if (isCompleted) el.classList.add("completed");
      if (isPast && !isCompleted && daySchedule) el.classList.add("missed");

      const dayLabel = document.createElement("div");
      dayLabel.className = "week-day-label";
      dayLabel.textContent = DAY_SHORT[i];

      const dateNum = document.createElement("div");
      dateNum.className = "week-day-num";
      dateNum.textContent = d.getDate();

      const indicator = document.createElement("div");
      indicator.className = "week-day-indicator";
      if (daySchedule) {
        if (isCompleted) {
          indicator.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#16a34a" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>`;
        } else {
          indicator.classList.add("has-workout");
          indicator.textContent = daySchedule.label ? daySchedule.label.charAt(0) : "W";
        }
      }

      el.appendChild(dayLabel);
      el.appendChild(dateNum);
      el.appendChild(indicator);

      el.addEventListener("click", () => {
        selectedDate = dateStr;
        // Ensure month grid shows this month
        const selMonth = d.getMonth() + 1;
        const selYear = d.getFullYear();
        if (selMonth !== currentMonth || selYear !== currentYear) {
          currentMonth = selMonth;
          currentYear = selYear;
          renderMonth();
        } else {
          buildGrid(monthDays); // just re-highlight
        }
        renderWeekStrip();
        renderDayPanel();
      });

      weekDays.appendChild(el);
    });
  }

  function formatShortDate(d) {
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${months[d.getMonth()]} ${d.getDate()}`;
  }

  /* ================================================================ */
  /*  Toggle completion                                                */
  /* ================================================================ */

  function toggleComplete(dateStr, completed) {
    fetch("/api/workout-plan/complete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ date: dateStr, completed }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          loadPlanThenRender();
        }
      });
  }

  /* ================================================================ */
  /*  Day panel — shows exercises for the selected day                 */
  /* ================================================================ */

  function renderDayPanel() {
    if (!activePlan || !activePlan.schedule) {
      todayPanel.hidden = true;
      return;
    }

    // Determine which day to show based on selectedDate
    const selDate = new Date(selectedDate + "T00:00:00");
    let wd = selDate.getDay();
    if (wd === 0) wd = 7;
    const dayName = DAY_NAMES_ORDER[wd - 1];
    const daySchedule = activePlan.schedule[dayName];

    if (!daySchedule) {
      todayPanel.hidden = true;
      return;
    }

    todayPanel.hidden = false;
    const todayStr = localTodayStr();
    const isToday = selectedDate === todayStr;
    const isPast = selectedDate < todayStr;
    const displayDate = selDate.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });

    if (isToday) {
      todayLabel.textContent = daySchedule.label
        ? `Today — ${daySchedule.label}`
        : `Today — ${dayName.charAt(0).toUpperCase() + dayName.slice(1)}`;
    } else {
      todayLabel.textContent = daySchedule.label
        ? `${displayDate} — ${daySchedule.label}`
        : displayDate;
    }

    // Completion state
    const completions = activePlan.completions || {};
    const alreadyDone = completions[selectedDate] && completions[selectedDate].completed;
    if (todayCompleteBtn) {
      if (alreadyDone) {
        todayCompleteBtn.hidden = false;
        todayCompleteBtn.textContent = "Completed";
        todayCompleteBtn.disabled = true;
        todayCompleteBtn.classList.add("done");
      } else {
        todayCompleteBtn.hidden = false;
        todayCompleteBtn.textContent = isPast ? "Mark Retroactive" : "Mark Complete";
        todayCompleteBtn.disabled = false;
        todayCompleteBtn.classList.remove("done");
        todayCompleteBtn.onclick = () => {
          toggleComplete(selectedDate, true);
        };
      }
    }

    todayExercises.innerHTML = "";

    (daySchedule.exercises || []).forEach(ex => {
      const card = document.createElement("div");
      card.className = "exercise-card";

      const imgHtml = ex.image_path
        ? `<img src="/exercises/images/${escapeHtml(ex.image_path)}" alt="${escapeHtml(ex.name)}" class="exercise-thumb" loading="lazy" />`
        : `<div class="exercise-thumb-placeholder"></div>`;

      const chevronDown = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>`;

      card.innerHTML = `
        ${imgHtml}
        <div class="exercise-info">
          <div class="exercise-name-row">
            <div class="exercise-name">${escapeHtml(ex.name)}</div>
            <button class="exercise-delete-btn" data-day="${escapeHtml(dayName)}" data-name="${escapeHtml(ex.name)}" title="Remove exercise">&times;</button>
          </div>
          <div class="exercise-meta">
            <span class="meta-pill">${ex.sets || "?"} sets</span>
            <span class="meta-pill">${ex.reps || "?"} reps</span>
            ${ex.equipment ? `<span class="meta-pill equip">${escapeHtml(ex.equipment)}</span>` : ""}
          </div>
          <button class="details-btn" data-name="${escapeHtml(ex.name)}">${chevronDown} Details</button>
        </div>
      `;
      todayExercises.appendChild(card);
    });

    // Wire up delete buttons
    todayExercises.querySelectorAll(".exercise-delete-btn").forEach(btn => {
      btn.addEventListener("click", handleDeleteExercise);
    });

    // Wire up details buttons
    todayExercises.querySelectorAll(".details-btn").forEach(btn => {
      btn.addEventListener("click", handleDetailsClick);
    });
  }

  /* ================================================================ */
  /*  Delete exercise                                                  */
  /* ================================================================ */

  function handleDeleteExercise(e) {
    e.stopPropagation();
    const btn = e.currentTarget;
    const day = btn.dataset.day;
    const name = btn.dataset.name;

    // Animate card removal
    const card = btn.closest(".exercise-card");
    if (card) {
      card.style.opacity = "0.4";
      card.style.pointerEvents = "none";
    }

    fetch("/api/workout-plan/exercise", {
      method: "DELETE",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ day: day, exercise_name: name }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          // Update local plan state and re-render
          activePlan = data.plan;
          lastPlanJSON = JSON.stringify(activePlan);
          renderMonth();
          renderWeekStrip();
          renderDayPanel();
        } else {
          // Restore card on failure
          if (card) {
            card.style.opacity = "";
            card.style.pointerEvents = "";
          }
        }
      })
      .catch(() => {
        if (card) {
          card.style.opacity = "";
          card.style.pointerEvents = "";
        }
      });
  }

  /* ================================================================ */
  /*  Exercise details expand/collapse                                 */
  /* ================================================================ */

  function handleDetailsClick(e) {
    const btn    = e.currentTarget;
    const name   = btn.dataset.name;
    const parent = btn.parentElement;

    const chevronDown = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>`;
    const chevronUp   = `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round"><polyline points="6 15 12 9 18 15"/></svg>`;

    if (btn.classList.contains("open")) {
      const det = parent.querySelector(".exercise-details");
      if (det) det.remove();
      btn.innerHTML = `${chevronDown} Details`;
      btn.classList.remove("open");
      return;
    }

    btn.innerHTML = `${chevronDown} Loading...`;
    fetch(`/api/workout-plan/exercise/${encodeURIComponent(name)}`)
      .then(r => r.json())
      .then(data => {
        if (!data.success) { btn.innerHTML = `${chevronDown} Details`; return; }
        const ex  = data.exercise;
        const det = document.createElement("div");
        det.className = "exercise-details";

        const steps = (ex.instructions || []).map(s => `<li>${escapeHtml(s)}</li>`).join("");
        det.innerHTML = `
          <div class="detail-row"><strong>Level:</strong> ${escapeHtml(ex.level || "N/A")} &middot; <strong>Category:</strong> ${escapeHtml(ex.category || "N/A")}</div>
          <div class="detail-row"><strong>Targets:</strong> ${escapeHtml((ex.primaryMuscles || []).join(", "))}</div>
          ${steps ? `<ol class="exercise-steps">${steps}</ol>` : ""}
        `;
        parent.appendChild(det);
        btn.innerHTML = `${chevronUp} Hide`;
        btn.classList.add("open");
      })
      .catch(() => { btn.innerHTML = `${chevronDown} Details`; });
  }

  /* ---- Utility ---- */
  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
  }

})();
