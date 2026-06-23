async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} failed`);
  return response.json();
}

const AUTO_REFRESH_MS = 30 * 60 * 1000;
let refreshInProgress = false;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return value.toFixed(digits);
  return value;
}

function pct(value) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(1)}%`;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `$${Number(value).toFixed(2)}`;
}

function daysSince(value) {
  if (!value) return "-";
  const opened = new Date(value);
  if (Number.isNaN(opened.getTime())) return "-";
  const ms = Date.now() - opened.getTime();
  return Math.max(0, Math.floor(ms / (24 * 60 * 60 * 1000)));
}

function spreadPct(row) {
  if (!row || !row.bid || !row.ask || !row.mid) return null;
  return (row.ask - row.bid) / row.mid;
}

function setRows(id, rows, render) {
  document.getElementById(id).innerHTML = rows.map((row, index) => render(row, index)).join("");
}

function buildStrategyIdeas(snapshot) {
  const universeByTicker = Object.fromEntries((snapshot.universe || []).map(row => [row.ticker, row]));
  const sectorByName = Object.fromEntries((snapshot.sectors || []).map(row => [row.sector, row]));
  const riskByTicker = Object.fromEntries((snapshot.risk || []).map(row => [row.ticker, row]));
  const bestByTicker = new Map();
  for (const option of snapshot.options || []) {
    const current = bestByTicker.get(option.ticker);
    if (!current || Number(option.total_score || 0) > Number(current.total_score || 0)) {
      bestByTicker.set(option.ticker, option);
    }
  }

  return Array.from(bestByTicker.values())
    .map(option => {
      const stock = universeByTicker[option.ticker] || {};
      const sector = sectorByName[stock.sector] || {};
      const risk = riskByTicker[option.ticker] || {};
      return { option, stock, sector, risk };
    })
    .sort((a, b) => Number(b.option.total_score || 0) - Number(a.option.total_score || 0));
}

function renderStrategyIdeas(snapshot) {
  const ideas = buildStrategyIdeas(snapshot);
  document.getElementById("ideaCount").textContent = `${ideas.length} ${ideas.length === 1 ? "idea" : "ideas"}`;
  const container = document.getElementById("strategyIdeas");
  if (!ideas.length) {
    container.innerHTML = `
      <div class="empty-state">
        No option ideas passed the tested strategy filters in the latest snapshot.
      </div>
    `;
    return;
  }

  container.innerHTML = ideas.map(({ option, stock, sector, risk }) => {
    const allowed = Boolean(risk.allowed);
    const spread = spreadPct(option);
    const reasonCodes = (risk.reason_codes || []).join(", ");
    return `
      <article class="idea-card ${allowed ? "allowed" : "blocked"}">
        <div class="idea-card-header">
          <div>
            <strong>${option.ticker}</strong>
            <span>${stock.sector || "Unmapped"}${sector.sector_rank ? ` rank ${sector.sector_rank}` : ""}</span>
          </div>
          <span class="status-pill ${allowed ? "status-allowed" : "status-blocked"}">${allowed ? "Risk allowed" : "Blocked"}</span>
        </div>
        <div class="contract-line">${option.contract_symbol}</div>
        <div class="idea-metrics">
          <div><span>Score</span><strong>${fmt(option.total_score)}</strong></div>
          <div><span>Stock</span><strong>${fmt(stock.stock_score)}</strong></div>
          <div><span>Sector</span><strong>${fmt(sector.sector_score)}</strong></div>
          <div><span>Premium</span><strong>${money(option.ask || option.mid)}</strong></div>
          <div><span>Spread</span><strong>${pct(spread)}</strong></div>
          <div><span>DTE</span><strong>${fmt(option.dte, 0)}</strong></div>
          <div><span>Delta</span><strong>${fmt(option.delta)}</strong></div>
          <div><span>Theta</span><strong>${fmt(option.theta)}</strong></div>
        </div>
        <div class="idea-footer">
          <span>${option.expiry} ${fmt(option.strike)}C</span>
          <span>${option.quote_quality || "live"} quote</span>
        </div>
        <p class="idea-note" title="${reasonCodes}">${risk.notes || option.score_details || "Manual validation required."}</p>
      </article>
    `;
  }).join("");
}

function scoreBreakdownHtml(row, detailId) {
  const breakdown = row.score_breakdown || {};
  const entries = Object.entries(breakdown);
  if (!entries.length) return "";
  const chips = entries.map(([name, value]) => `
    <span class="score-chip ${value >= 0 ? "positive" : "negative"}">
      ${name.replaceAll("_", " ")}: ${fmt(value)}
    </span>
  `).join("");
  return `
    <tr class="score-detail-row" id="${detailId}" hidden>
      <td colspan="19">
        <div class="score-panel">
          <div class="score-breakdown">${chips}</div>
          <p>${row.score_details || ""}</p>
        </div>
      </td>
    </tr>
  `;
}

function toggleScore(id) {
  const row = document.getElementById(id);
  if (row) row.hidden = !row.hidden;
}

async function loadSnapshot(refresh = false) {
  const errorBanner = document.getElementById("errorBanner");
  errorBanner.hidden = true;
  let snapshot;
  try {
    snapshot = await fetchJson(refresh ? "/api/signals/refresh" : "/api/signals/latest");
  } catch (error) {
    errorBanner.textContent = "Dashboard data failed to load. Run python -m src.main --mode live-snapshot, then restart python -m src.main --mode live-dashboard.";
    errorBanner.hidden = false;
    throw error;
  }
  if (snapshot.refresh_error) {
    errorBanner.textContent = snapshot.refresh_error;
    errorBanner.hidden = false;
  }
  document.getElementById("provider").textContent = snapshot.provider;
  document.getElementById("asOf").textContent = snapshot.as_of;
  document.getElementById("marketStatus").textContent = snapshot.market_status;
  document.getElementById("regimeStatus").textContent = snapshot.regime_status;
  renderStrategyIdeas(snapshot);

  setRows("sectors", snapshot.sectors, row => `
    <tr><td>${row.sector_rank}</td><td>${row.sector}</td><td>${row.etf}</td><td>${fmt(row.sector_score)}</td><td>${pct(row.return_1w)}</td><td>${pct(row.return_1m)}</td><td>${pct(row.return_3m)}</td><td>${row.selected ? "Yes" : "No"}</td></tr>
  `);
  setRows("universe", snapshot.universe, row => `
    <tr><td>${row.ticker}</td><td>${row.sector}</td><td>${fmt(row.stock_score)}</td><td>${fmt(row.momentum_score)}</td><td>${fmt(row.last_price)}</td><td>${row.selected ? "Yes" : "No"}</td></tr>
  `);
  setRows("options", snapshot.options, (row, index) => {
    const detailId = `score-detail-${index}`;
    return `
      <tr><td>${row.ticker}</td><td>${row.contract_symbol}</td><td>${row.expiry}</td><td>${fmt(row.strike)}</td><td>${fmt(row.bid)}</td><td>${fmt(row.ask)}</td><td>${fmt(row.delta)}</td><td>${fmt(row.theta)}</td><td>${fmt(row.implied_vol)}</td><td>${fmt(row.open_interest, 0)}</td><td>${fmt(row.dte, 0)}</td><td><button class="score-button" type="button" onclick="toggleScore('${detailId}')">${fmt(row.total_score)}</button></td><td>${fmt(row.momentum_score)}</td><td>${fmt(row.liquidity_score)}</td><td>${fmt(row.theta_efficiency_score)}</td><td>${fmt(row.delta_score)}</td><td>${fmt(row.iv_score)}</td><td>${fmt(row.dte_score)}</td><td>${row.quote_quality || "live"}</td></tr>
      ${scoreBreakdownHtml(row, detailId)}
    `;
  });
  setRows("optionDiagnostics", snapshot.option_diagnostics || [], row => `
    <tr title="${row.notes || ""}"><td>${row.ticker}</td><td>${fmt(row.last_price)}</td><td>${(row.available_expiries || []).length}</td><td>${(row.selected_expiries || []).join(", ") || "-"}</td><td>${row.calls_before_filters}</td><td>${row.after_strike_filter}</td><td>${row.after_quote_filter}</td><td>${row.after_iv_filter}</td><td>${row.after_greeks_filter}</td><td>${row.failure_reason || "OK"}</td><td>${row.notes}</td></tr>
  `);
  setRows("risk", snapshot.risk, row => `
    <tr><td>${row.ticker}</td><td>${row.allowed ? "Yes" : "No"}</td><td>${row.reason_codes.join(", ")}</td><td>${fmt(row.position_size_multiplier)}</td><td>${row.notes}</td></tr>
  `);
}

async function loadJournal() {
  const journal = await fetchJson("/api/journal");
  setRows("journal", journal.slice(-20).reverse(), row => `
    <tr><td>${row.timestamp || "-"}</td><td>${row.ticker || "-"}</td><td>${row.contract_symbol || "-"}</td><td>${row.trade_taken || "-"}</td><td>${row.manual_notes || ""}</td></tr>
  `);
}

async function loadRecommendations() {
  const [recommendations, reviewRows, openRows, closedRows, sectors] = await Promise.all([
    fetchJson("/api/recommendations?limit=50"),
    fetchJson("/api/recommendations/review-required"),
    fetchJson("/api/recommendations/open"),
    fetchJson("/api/recommendations/closed?limit=50"),
    fetchJson("/api/recommendations/sectors")
  ]);
  document.getElementById("recommendationCount").textContent = `${recommendations.length} ${recommendations.length === 1 ? "record" : "records"}`;
  renderBestRecommendation(openRows);
  setRows("reviewRequiredRecommendations", reviewRows, row => `
    <tr title="${row.latest_notes || row.notes || ""}">
      <td>${row.ticker || "-"}</td>
      <td>${row.option_symbol || "-"}</td>
      <td>${money(row.ask || row.mid)}</td>
      <td>${fmt(row.recommendation_score)}</td>
      <td>${pct(spreadPct(row))}</td>
      <td>${fmt(row.dte, 0)}</td>
      <td>${row.latest_notes || row.notes || ""}</td>
      <td><button class="score-button" type="button" onclick="approveRecommendation(${row.id}, ${Number(row.ask || row.mid || 0)})">Approve</button></td>
    </tr>
  `);
  setRows("openRecommendations", openRows, row => `
    <tr title="${row.latest_notes || row.notes || ""}">
      <td>${row.ticker || "-"}</td>
      <td>${row.option_symbol || "-"}</td>
      <td><span class="status-pill status-open">${row.status || "-"}</span></td>
      <td>${money(row.entry_price)}</td>
      <td>${money(row.current_price)}</td>
      <td class="${Number(row.pnl_pct || 0) >= 0 ? "positive-text" : "negative-text"}">${pct(row.pnl_pct)}</td>
      <td>${daysSince(row.opened_at)}</td>
      <td>Target 40% / Stop -25%</td>
      <td>${row.latest_notes || row.notes || ""}</td>
    </tr>
  `);
  setRows("closedRecommendations", closedRows, row => `
    <tr title="${row.latest_notes || row.notes || ""}">
      <td>${row.ticker || "-"}</td>
      <td>${row.option_symbol || "-"}</td>
      <td>${money(row.entry_price)}</td>
      <td>${money(row.close_price)}</td>
      <td class="${Number(row.pnl_pct || 0) >= 0 ? "positive-text" : "negative-text"}">${pct(row.pnl_pct)}</td>
      <td>${row.close_reason || "-"}</td>
      <td>${row.opened_at || "-"}</td>
      <td>${row.closed_at || "-"}</td>
    </tr>
  `);
  setRows("recommendations", recommendations, row => `
    <tr title="${row.notes || ""}">
      <td>${row.timestamp || "-"}</td>
      <td>${row.ticker || "-"}</td>
      <td>${row.sector || "-"}</td>
      <td>${row.option_symbol || "-"}</td>
      <td>${fmt(row.recommendation_score)}</td>
      <td>${row.status || row.recommendation_type || "-"}</td>
    </tr>
  `);
  setRows("recommendationSectors", sectors, row => `
    <tr>
      <td>${row.sector || "-"}</td>
      <td>${fmt(row.recommendation_count, 0)}</td>
      <td>${fmt(row.average_score)}</td>
    </tr>
  `);
}

async function approveRecommendation(id, entryPrice) {
  await fetchJson(`/api/recommendations/${id}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      entry_price: entryPrice,
      notes: "Manually approved for paper trade."
    })
  });
  await loadRecommendations();
}

function renderBestRecommendation(openRows) {
  const container = document.getElementById("bestRecommendation");
  if (!openRows.length) {
    container.innerHTML = `<div class="empty-state">No open recommendation is currently being tracked.</div>`;
    return;
  }
  const best = [...openRows].sort((a, b) => Number(b.recommendation_score || 0) - Number(a.recommendation_score || 0))[0];
  container.innerHTML = `
    <article class="best-panel">
      <div>
        <span>Best Probability-of-Profit</span>
        <strong>${best.ticker || "-"} ${best.option_symbol || ""}</strong>
      </div>
      <div><span>Score</span><strong>${fmt(best.recommendation_score)}</strong></div>
      <div><span>Entry Ask</span><strong>${money(best.entry_price)}</strong></div>
      <div><span>Current</span><strong>${money(best.current_price)}</strong></div>
      <div><span>PnL</span><strong class="${Number(best.pnl_pct || 0) >= 0 ? "positive-text" : "negative-text"}">${pct(best.pnl_pct)}</strong></div>
      <div><span>Days Open</span><strong>${daysSince(best.opened_at)}</strong></div>
    </article>
  `;
}

async function refreshDashboard(refreshSnapshot = false, source = "manual") {
  if (refreshInProgress) return;
  const refreshButton = document.getElementById("refresh");
  const refreshStatus = document.getElementById("refreshStatus");
  refreshInProgress = true;
  refreshButton.disabled = true;
  refreshStatus.textContent = source === "auto" ? "Auto refresh running..." : "Refresh running...";
  try {
    await loadSnapshot(refreshSnapshot);
    await loadRecommendations();
    refreshStatus.textContent = `Last ${source} refresh: ${new Date().toLocaleString()}`;
  } catch (error) {
    refreshStatus.textContent = `Refresh failed: ${new Date().toLocaleString()}`;
    throw error;
  } finally {
    refreshInProgress = false;
    refreshButton.disabled = false;
  }
}

document.getElementById("refresh").addEventListener("click", () => {
  refreshDashboard(true, "manual").catch(error => console.error(error));
});
document.getElementById("journalForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  for (const name of ["risk_allowed", "platform_validated", "chart_validated", "trade_taken"]) {
    payload[name] = form.has(name);
  }
  await fetchJson("/api/journal", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  event.target.reset();
  await loadJournal();
});

refreshDashboard(false, "initial").catch(error => console.error(error));
loadJournal().catch(error => console.error(error));
setInterval(() => {
  refreshDashboard(true, "auto").catch(error => console.error(error));
}, AUTO_REFRESH_MS);
