/*********************************************************************
 *  nutrition.js — Nutrition Planner UI
 *
 *  Manages profile, meal plans, pantry, grocery lists, and nutrient
 *  checks via the nutrition API endpoints.
 *********************************************************************/

(function () {
  "use strict";

  /* ---- DOM refs ---- */
  const tabs = document.querySelectorAll(".nutrition-tab");
  const panels = document.querySelectorAll(".nutrition-panel");
  const profileForm = document.getElementById("profileForm");
  const profileStatus = document.getElementById("profileStatus");
  const profileCards = document.getElementById("profileCards");
  const profileMissing = document.getElementById("profileMissing");
  const editDetailsBtn = document.getElementById("editDetailsBtn");
  const profileFormWrapper = document.getElementById("profileFormWrapper");
  const planInfo = document.getElementById("planInfo");
  const planDetails = document.getElementById("planDetails");
  const createPlanBtn = document.getElementById("createPlanBtn");
  const modifyPlanBtn = document.getElementById("modifyPlanBtn");
  const planLoading = document.getElementById("planLoading");
  const pantryList = document.getElementById("pantryList");
  const pantryItemName = document.getElementById("pantryItemName");
  const pantryItemQty = document.getElementById("pantryItemQty");
  const pantryItemCat = document.getElementById("pantryItemCat");
  const addPantryBtn = document.getElementById("addPantryBtn");
  const groceryList = document.getElementById("groceryList");
  const nutrientInfo = document.getElementById("nutrientInfo");
  const checkNutrientsBtn = document.getElementById("checkNutrientsBtn");

  let currentPantryItems = [];

  /* ================================================================ */
  /*  Tab switching                                                    */
  /* ================================================================ */

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      tabs.forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      panels.forEach(p => { p.hidden = true; });
      const panel = document.getElementById("panel-" + target);
      if (panel) panel.hidden = false;

      if (target === "plan") loadPlan();
      if (target === "pantry") loadPantry();
      if (target === "grocery") loadGrocery();
      if (target === "nutrients") loadNutrients();
    });
  });

  /* ================================================================ */
  /*  Profile                                                          */
  /* ================================================================ */

  function loadProfile() {
    fetch("/api/nutrition-profile")
      .then(r => r.json())
      .then(data => {
        if (!data.success || !data.profile) {
          renderProfileCards(null);
          loadCompleteness();
          return;
        }
        const p = data.profile;
        setVal("age", p.age);
        setVal("sex", p.sex);
        setVal("weight_kg", p.weight_kg);
        setVal("height_cm", p.height_cm);
        setVal("activity_level", p.activity_level);
        setVal("weekly_budget_usd", p.weekly_budget_usd);
        setVal("allergies", (p.allergies || []).join(", "));
        setVal("dietary_preferences", (p.dietary_preferences || []).join(", "));
        setVal("health_goals", (p.health_goals || []).join(", "));
        const lab = p.lab_values || {};
        setVal("vitamin_d_ng_ml", lab.vitamin_d_ng_ml);
        setVal("iron_ug_dl", lab.iron_ug_dl);
        setVal("cholesterol_total_mg_dl", lab.cholesterol_total_mg_dl);
        setVal("ldl_mg_dl", lab.ldl_mg_dl);
        setVal("hdl_mg_dl", lab.hdl_mg_dl);
        setVal("b12_pg_ml", lab.b12_pg_ml);
        setVal("hba1c_pct", lab.hba1c_pct);
        renderProfileCards(p);
        loadCompleteness();
      })
      .catch(() => {});
  }

  function setVal(name, value) {
    const el = profileForm.querySelector(`[name="${name}"]`);
    if (el && value !== null && value !== undefined) el.value = value;
  }

  function getVal(name) {
    const el = profileForm.querySelector(`[name="${name}"]`);
    return el ? el.value : "";
  }

  function parseList(str) {
    return str.split(",").map(s => s.trim()).filter(Boolean);
  }

  function parseNum(str) {
    const n = parseFloat(str);
    return isNaN(n) ? null : n;
  }

  profileForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const body = {
      age: parseInt(getVal("age")) || 30,
      weight_kg: parseFloat(getVal("weight_kg")) || 70,
      height_cm: parseFloat(getVal("height_cm")) || 170,
      sex: getVal("sex") || "male",
      activity_level: getVal("activity_level") || "moderate",
      weekly_budget_usd: parseNum(getVal("weekly_budget_usd")),
      allergies: parseList(getVal("allergies")),
      dietary_preferences: parseList(getVal("dietary_preferences")),
      health_goals: parseList(getVal("health_goals")),
      lab_values: {
        vitamin_d_ng_ml: parseNum(getVal("vitamin_d_ng_ml")),
        iron_ug_dl: parseNum(getVal("iron_ug_dl")),
        cholesterol_total_mg_dl: parseNum(getVal("cholesterol_total_mg_dl")),
        ldl_mg_dl: parseNum(getVal("ldl_mg_dl")),
        hdl_mg_dl: parseNum(getVal("hdl_mg_dl")),
        b12_pg_ml: parseNum(getVal("b12_pg_ml")),
        hba1c_pct: parseNum(getVal("hba1c_pct")),
      },
    };
    fetch("/api/nutrition-profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(r => r.json())
      .then(data => {
        profileStatus.textContent = data.success ? "Profile saved!" : (data.message || "Error saving profile.");
        profileStatus.className = "nutrition-status " + (data.success ? "success" : "error");
        setTimeout(() => { profileStatus.textContent = ""; }, 3000);
      })
      .catch(() => {
        profileStatus.textContent = "Network error.";
        profileStatus.className = "nutrition-status error";
      });
  });

  loadProfile();

  /* ================================================================ */
  /*  Meal Plan                                                        */
  /* ================================================================ */

  function loadPlan() {
    fetch("/api/nutrition-plan")
      .then(r => r.json())
      .then(data => {
        if (!data.success || !data.plan) {
          planInfo.innerHTML = '<p class="empty-state">No meal plan yet. Create one below or ask in chat.</p>';
          modifyPlanBtn.hidden = true;
          return;
        }
        renderPlan(data.plan);
        modifyPlanBtn.hidden = false;
      })
      .catch(() => {
        planInfo.innerHTML = '<p class="empty-state">Error loading plan.</p>';
      });
  }

  function renderPlan(plan) {
    let html = `<div class="plan-title-bar"><strong>${escapeHtml(plan.title || "Meal Plan")}</strong></div>`;
    const targets = plan.daily_targets || {};
    if (targets.calories) {
      html += `<div class="plan-targets">Daily: ${targets.calories} kcal | P: ${targets.protein_g || "?"}g | C: ${targets.carbs_g || "?"}g | F: ${targets.fat_g || "?"}g | Fiber: ${targets.fiber_g || "?"}g</div>`;
    }
    const days = plan.days || {};
    for (const [day, dayData] of Object.entries(days)) {
      html += `<div class="plan-day"><h3>${capitalize(day)}</h3>`;
      const meals = dayData.meals || [];
      meals.forEach(meal => {
        html += `<div class="plan-meal">`;
        html += `<div class="meal-header"><span class="meal-type">${escapeHtml(meal.meal_type || "")}</span> <strong>${escapeHtml(meal.name || "")}</strong></div>`;
        html += `<div class="meal-macros">${meal.calories || 0} kcal | P: ${meal.protein_g || 0}g | C: ${meal.carbs_g || 0}g | F: ${meal.fat_g || 0}g</div>`;
        if (meal.prep_time_min) {
          html += `<div class="meal-prep">Prep: ${meal.prep_time_min} min</div>`;
        }
        if (meal.ingredients && meal.ingredients.length) {
          html += `<div class="meal-ingredients"><em>Ingredients:</em> ${meal.ingredients.map(i => escapeHtml(i.name + (i.amount ? " (" + i.amount + ")" : ""))).join(", ")}</div>`;
        }
        if (meal.recipe_steps && meal.recipe_steps.length) {
          html += `<details class="meal-recipe"><summary>Recipe</summary><ol>`;
          meal.recipe_steps.forEach(step => {
            html += `<li>${escapeHtml(step)}</li>`;
          });
          html += `</ol></details>`;
        }
        html += `</div>`;
      });
      html += `</div>`;
    }

    const alerts = plan.nutrient_alerts || [];
    const realAlerts = alerts.filter(a => a.status !== "unknown");
    if (realAlerts.length) {
      html += `<div class="plan-alerts"><h3>Nutrient Alerts</h3><ul>`;
      realAlerts.forEach(a => {
        html += `<li><strong>${escapeHtml(a.nutrient)}:</strong> ${escapeHtml(a.message)}`;
        if (a.food_suggestions && a.food_suggestions.length) {
          html += ` <em>(Try: ${a.food_suggestions.slice(0, 4).map(escapeHtml).join(", ")})</em>`;
        }
        html += `</li>`;
      });
      html += `</ul></div>`;
    }

    planInfo.innerHTML = html;
  }

  createPlanBtn.addEventListener("click", () => {
    const details = planDetails.value.trim() || "Create a balanced 7-day meal plan";
    planLoading.hidden = false;
    createPlanBtn.disabled = true;
    fetch("/api/nutrition-plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ details }),
    })
      .then(r => r.json())
      .then(data => {
        planLoading.hidden = true;
        createPlanBtn.disabled = false;
        if (data.success && data.plan) {
          renderPlan(data.plan);
          modifyPlanBtn.hidden = false;
        } else {
          planInfo.innerHTML = `<p class="empty-state">${escapeHtml(data.message || "Error creating plan.")}</p>`;
        }
      })
      .catch(() => {
        planLoading.hidden = true;
        createPlanBtn.disabled = false;
        planInfo.innerHTML = '<p class="empty-state">Network error creating plan.</p>';
      });
  });

  modifyPlanBtn.addEventListener("click", () => {
    const details = planDetails.value.trim();
    if (!details) {
      planDetails.placeholder = "Describe the modification you want...";
      planDetails.focus();
      return;
    }
    planLoading.hidden = false;
    planLoading.textContent = "Modifying meal plan...";
    modifyPlanBtn.disabled = true;
    fetch("/api/nutrition-plan", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ details }),
    })
      .then(r => r.json())
      .then(data => {
        planLoading.hidden = true;
        planLoading.textContent = "Generating meal plan...";
        modifyPlanBtn.disabled = false;
        if (data.success && data.plan) {
          renderPlan(data.plan);
        } else {
          planInfo.innerHTML = `<p class="empty-state">${escapeHtml(data.message || "Error modifying plan.")}</p>`;
        }
      })
      .catch(() => {
        planLoading.hidden = true;
        planLoading.textContent = "Generating meal plan...";
        modifyPlanBtn.disabled = false;
      });
  });

  /* ================================================================ */
  /*  Pantry                                                           */
  /* ================================================================ */

  function loadPantry() {
    fetch("/api/nutrition-pantry")
      .then(r => r.json())
      .then(data => {
        if (!data.success) return;
        currentPantryItems = (data.pantry && data.pantry.items) ? data.pantry.items : [];
        renderPantry();
      })
      .catch(() => {});
  }

  function renderPantry() {
    if (!currentPantryItems.length) {
      pantryList.innerHTML = '<p class="empty-state">Pantry is empty. Add items below.</p>';
      return;
    }
    let html = '<div class="pantry-items">';
    currentPantryItems.forEach((item, idx) => {
      const cat = (item.category || "other").replace("_", " ");
      html += `<div class="pantry-item">
        <span class="pantry-item-name">${escapeHtml(item.name)}</span>
        <span class="pantry-item-qty">${escapeHtml(item.quantity || "")}</span>
        <span class="pantry-item-cat">${escapeHtml(cat)}</span>
        <button class="pantry-remove-btn" data-idx="${idx}">x</button>
      </div>`;
    });
    html += '</div>';
    pantryList.innerHTML = html;

    pantryList.querySelectorAll(".pantry-remove-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        const idx = parseInt(btn.dataset.idx);
        currentPantryItems.splice(idx, 1);
        savePantry();
        renderPantry();
      });
    });
  }

  function savePantry() {
    fetch("/api/nutrition-pantry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: currentPantryItems }),
    }).catch(() => {});
  }

  addPantryBtn.addEventListener("click", () => {
    const name = pantryItemName.value.trim();
    if (!name) return;
    currentPantryItems.push({
      name: name,
      quantity: pantryItemQty.value.trim() || "1",
      category: pantryItemCat.value,
    });
    pantryItemName.value = "";
    pantryItemQty.value = "";
    savePantry();
    renderPantry();
  });

  /* ================================================================ */
  /*  Grocery List                                                     */
  /* ================================================================ */

  function loadGrocery() {
    fetch("/api/nutrition-plan/grocery-list")
      .then(r => r.json())
      .then(data => {
        if (!data.success || !data.grocery_list || !data.grocery_list.length) {
          groceryList.innerHTML = '<p class="empty-state">Create a meal plan first to generate a grocery list.</p>';
          return;
        }
        renderGrocery(data.grocery_list);
      })
      .catch(() => {
        groceryList.innerHTML = '<p class="empty-state">Error loading grocery list.</p>';
      });
  }

  function renderGrocery(items) {
    const byCategory = {};
    let totalCost = 0;
    items.forEach(item => {
      const cat = (item.category || "other").replace("_", " ");
      if (!byCategory[cat]) byCategory[cat] = [];
      byCategory[cat].push(item);
      if (item.estimated_cost_usd) totalCost += item.estimated_cost_usd;
    });

    let html = '';
    Object.keys(byCategory).sort().forEach(cat => {
      html += `<div class="grocery-category"><h3>${capitalize(cat)}</h3><ul>`;
      byCategory[cat].forEach(item => {
        const cost = item.estimated_cost_usd ? ` (~$${item.estimated_cost_usd.toFixed(2)})` : "";
        html += `<li>${escapeHtml((item.name || "").charAt(0).toUpperCase() + (item.name || "").slice(1))}: ${escapeHtml(item.amount || "")}${cost}</li>`;
      });
      html += `</ul></div>`;
    });

    if (totalCost > 0) {
      html += `<div class="grocery-total"><strong>Estimated total: $${totalCost.toFixed(2)}</strong></div>`;
    }

    groceryList.innerHTML = html;
  }

  /* ================================================================ */
  /*  Nutrient Check                                                   */
  /* ================================================================ */

  function loadNutrients() {
    fetch("/api/nutrition-plan/nutrient-gaps")
      .then(r => r.json())
      .then(data => {
        if (!data.success) {
          nutrientInfo.innerHTML = `<p class="empty-state">${escapeHtml(data.message || "Set up your profile first.")}</p>`;
          return;
        }
        renderNutrients(data.gaps || []);
      })
      .catch(() => {
        nutrientInfo.innerHTML = '<p class="empty-state">Error loading nutrient data.</p>';
      });
  }

  function renderNutrients(gaps) {
    if (!gaps.length) {
      nutrientInfo.innerHTML = '<p class="empty-state">No nutrient gaps detected based on available data.</p>';
      return;
    }
    let html = '<div class="nutrient-gaps">';
    gaps.forEach(gap => {
      const statusClass = gap.status === "low" ? "gap-low" : gap.status === "high" ? "gap-high" : "gap-unknown";
      html += `<div class="nutrient-gap ${statusClass}">`;
      html += `<strong>${escapeHtml(gap.nutrient)}</strong>: ${escapeHtml(gap.message)}`;
      if (gap.food_suggestions && gap.food_suggestions.length) {
        html += `<div class="gap-suggestions">Try: ${gap.food_suggestions.slice(0, 4).map(escapeHtml).join(", ")}</div>`;
      }
      html += `</div>`;
    });
    html += '</div>';
    nutrientInfo.innerHTML = html;
  }

  checkNutrientsBtn.addEventListener("click", loadNutrients);

  /* ================================================================ */
  /*  Profile Cards & Completeness                                    */
  /* ================================================================ */

  function loadCompleteness() {
    fetch("/api/nutrition-profile/completeness")
      .then(r => r.json())
      .then(data => {
        if (!data.success) return;
        const circle = document.getElementById("completenessCircle");
        const text = document.getElementById("completenessText");
        if (circle) circle.setAttribute("stroke-dasharray", data.score + ", 100");
        if (text) text.textContent = data.score + "%";

        if (profileMissing && data.missing_suggestions && data.missing_suggestions.length) {
          let html = '<span class="hint-label">Help me learn more:</span> ';
          data.missing_suggestions.forEach(s => {
            html += '<span class="hint-chip">' + escapeHtml(s) + '</span>';
          });
          profileMissing.innerHTML = html;
        } else if (profileMissing) {
          profileMissing.innerHTML = "";
        }
      })
      .catch(() => {});
  }

  const _fieldLabels = {
    age: "Age", weight_kg: "Weight", height_cm: "Height", sex: "Sex",
    activity_level: "Activity", allergies: "Allergies",
    dietary_preferences: "Diet Preferences", health_goals: "Health Goals",
    weekly_budget_usd: "Budget", lab_values: "Lab Values"
  };

  const _fieldGroups = {
    "Body Stats": ["age", "weight_kg", "height_cm", "sex"],
    "Lifestyle": ["activity_level", "weekly_budget_usd"],
    "Preferences & Goals": ["dietary_preferences", "allergies", "health_goals"],
    "Lab Values": ["lab_values"]
  };

  const _defaults = {
    age: 30, weight_kg: 70.0, height_cm: 170.0, sex: "male",
    activity_level: "moderate", allergies: [], dietary_preferences: [],
    health_goals: [], weekly_budget_usd: null, lab_values: {}
  };

  function renderProfileCards(profile) {
    if (!profileCards) return;
    if (!profile) {
      profileCards.innerHTML = '<div class="empty-state">No profile data yet. Chat with the assistant or click Edit Details to get started.</div>';
      return;
    }
    const meta = profile.insight_meta || {};
    let html = "";

    for (const [groupName, fields] of Object.entries(_fieldGroups)) {
      let chips = "";
      fields.forEach(key => {
        const val = profile[key];
        const def = _defaults[key];
        let display = "";
        let filled = false;

        if (key === "lab_values" && typeof val === "object" && val) {
          const filledLabs = Object.entries(val).filter(([, v]) => v !== null);
          if (filledLabs.length) {
            filled = true;
            display = filledLabs.map(([k, v]) => k.replace(/_/g, " ") + ": " + v).join(", ");
          }
        } else if (Array.isArray(val)) {
          if (val.length > 0) { filled = true; display = val.join(", "); }
        } else if (val !== null && val !== undefined && val !== def) {
          filled = true;
          display = key === "weekly_budget_usd" ? "$" + val : String(val);
        }

        if (filled) {
          const source = meta[key] && meta[key].source === "chat" ? ' <span class="chip-source" title="Learned from conversation">&#x1f4ac;</span>' : "";
          chips += '<div class="profile-chip">'
            + '<span class="chip-label">' + escapeHtml(_fieldLabels[key] || key) + '</span> '
            + '<span class="chip-value">' + escapeHtml(display) + '</span>'
            + source
            + ' <button class="chip-delete" data-field="' + key + '" title="Remove">&times;</button>'
            + '</div>';
        }
      });

      if (chips) {
        html += '<div class="card-group"><h4>' + escapeHtml(groupName) + '</h4><div class="card-chips">' + chips + '</div></div>';
      }
    }

    if (!html) {
      profileCards.innerHTML = '<div class="empty-state">No profile data yet. Chat with the assistant or click Edit Details to get started.</div>';
    } else {
      profileCards.innerHTML = html;
    }

    // Wire delete buttons
    profileCards.querySelectorAll(".chip-delete").forEach(btn => {
      btn.addEventListener("click", () => deleteProfileField(btn.dataset.field));
    });
  }

  function deleteProfileField(fieldName) {
    const resetData = {};
    if (fieldName === "lab_values") {
      resetData.lab_values = {
        vitamin_d_ng_ml: null, iron_ug_dl: null,
        cholesterol_total_mg_dl: null, ldl_mg_dl: null,
        hdl_mg_dl: null, b12_pg_ml: null, hba1c_pct: null
      };
    } else if (Array.isArray(_defaults[fieldName])) {
      resetData[fieldName] = [];
    } else {
      resetData[fieldName] = _defaults[fieldName];
    }
    resetData.insight_meta = { [fieldName]: null };
    fetch("/api/nutrition-profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(resetData),
    })
      .then(r => r.json())
      .then(() => loadProfile())
      .catch(() => {});
  }

  // Edit Details toggle
  if (editDetailsBtn && profileFormWrapper) {
    editDetailsBtn.addEventListener("click", () => {
      const hidden = profileFormWrapper.hidden;
      profileFormWrapper.hidden = !hidden;
      editDetailsBtn.textContent = hidden ? "Hide Form" : "Edit Details";
    });
  }

  /* ---- Utility ---- */
  function escapeHtml(str) {
    if (!str) return "";
    return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function capitalize(str) {
    if (!str) return "";
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

})();
