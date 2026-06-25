async function fetchUltraShortJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${url} failed with ${response.status}`);
  return response.json();
}

const ULTRA_SHORT_AUTO_REFRESH_MS = 30 * 60 * 1000;
const ULTRA_SHORT_AUTO_REFRESH_LABEL = "30 minutes";
let ultraShortRefreshInProgress = false;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return value.toFixed(digits);
  return value;
}

function pct(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `$${Number(value).toFixed(2)}`;
}

function setRows(id, rows, render, emptyText) {
  const body = document.getElementById(id);
  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="12" class="empty-table">${emptyText}</td></tr>`;
    return;
  }
  body.innerHTML = rows.map(render).join("");
}

function bestSetupRows(rows, direction) {
  const bestByTicker = new Map();
  for (const row of rows || []) {
    if (row.direction !== direction || !["GENERATED", "REVIEW_REQUIRED"].includes(row.status)) continue;
    const current = bestByTicker.get(row.ticker);
    const rowRank = (row.contract_symbol ? 1000 : 0) + (row.status === "REVIEW_REQUIRED" ? 100 : 0) + Number(row.ultra_short_score || 0);
    const currentRank = current ? (current.contract_symbol ? 1000 : 0) + (current.status === "REVIEW_REQUIRED" ? 100 : 0) + Number(current.ultra_short_score || 0) : -1;
    if (!current || rowRank > currentRank) bestByTicker.set(row.ticker, row);
  }
  return [...bestByTicker.values()].sort((a, b) => Number(b.ultra_short_score || 0) - Number(a.ultra_short_score || 0));
}

async function loadUltraShortPortal() {
  const snapshot = await fetchUltraShortJson("/api/ultra-short/snapshot");
  const candidates = await fetchUltraShortJson("/api/ultra-short/candidates?limit=100");
  const trades = await fetchUltraShortJson("/api/ultra-short/paper-trades");
  const marks = await fetchUltraShortJson("/api/ultra-short/marks");
  const analytics = await fetchUltraShortJson("/api/ultra-short/analytics");
  document.getElementById("ultraShortStatus").textContent = snapshot.warning || "Portal shell";
  document.getElementById("labMode").textContent = snapshot.mode || "-";
  document.getElementById("labAsOf").textContent = snapshot.as_of || "-";
  document.getElementById("marketMode").textContent = snapshot.market_bias?.mode || "-";
  document.getElementById("nextPhase").textContent = snapshot.implementation_phase?.current || snapshot.implementation_phase?.next || "-";
  document.getElementById("callReadiness").textContent = fmt(snapshot.market_bias?.call_readiness);
  document.getElementById("putReadiness").textContent = fmt(snapshot.market_bias?.put_readiness);
  document.getElementById("biasStatus").textContent = snapshot.status || "-";
  document.getElementById("biasNotes").textContent = snapshot.market_bias?.notes || "-";

  setRows("intradaySectors", snapshot.intraday_sectors, row => `
    <tr>
      <td>${fmt(row.rank, 0)}</td>
      <td>${row.sector || "-"}</td>
      <td>${row.etf || "-"}</td>
      <td>${pct(row.today_return)}</td>
      <td>${row.trend_60m || "-"}</td>
      <td>${row.vwap_state || "-"}</td>
      <td>${fmt(row.relative_strength)}</td>
      <td>${row.ultra_short_bias || "-"}</td>
    </tr>
  `, "Intraday sector scoring will appear after a live snapshot is available.");

  const persistedCalls = bestSetupRows(candidates, "CALL");
  const persistedPuts = bestSetupRows(candidates, "PUT");

  const setupRenderer = row => `
    <tr>
      <td>${row.ticker || "-"}</td>
      <td>${row.contract_symbol || "-"}</td>
      <td>${row.expiry || "-"}</td>
      <td>${money(row.suggested_premium)}</td>
      <td>${fmt(row.delta)}</td>
      <td>${pct(row.spread_pct)}</td>
      <td>${fmt(row.dte, 0)}</td>
      <td>${row.setup_state || row.status || "-"}</td>
      <td>${row.entry_trigger || "-"}</td>
      <td>${fmt(row.ultra_short_score)}</td>
      <td>
        ${row.status === "REVIEW_REQUIRED" ? `
          <button class="score-button" type="button" onclick="approveUltraShortCandidate(${row.id}, ${Number(row.ask || row.suggested_premium || 0)})">Review</button>
          <button class="score-button reject-button" type="button" onclick="rejectUltraShortCandidate(${row.id})">Reject</button>
        ` : row.status || "-"}
      </td>
    </tr>
  `;
  setRows("callSetups", persistedCalls, setupRenderer, "Call setup candidates will appear after the ultra-short snapshot service is connected.");
  setRows("putSetups", persistedPuts, setupRenderer, "Put setup candidates will appear after the ultra-short snapshot service is connected.");

  setRows("activeTrades", trades.active_trades, row => `
    <tr>
      <td>${row.ticker || "-"}</td>
      <td>${row.contract_symbol || "-"}</td>
      <td>${row.state || "-"}</td>
      <td>${money(row.entry_price)}</td>
      <td>${money(row.current_price)}</td>
      <td>${pct(row.pnl_pct)}</td>
      <td>${row.vwap_invalidation || "-"}</td>
      <td>${money(row.stop_price)}</td>
      <td>${row.exit_signal || "-"}</td>
    </tr>
  `, "No active ultra-short paper trades.");

  setRows("closedTrades", trades.closed_trades, row => `
    <tr>
      <td>${row.ticker || "-"}</td>
      <td>${row.contract_symbol || "-"}</td>
      <td>${money(row.entry_price)}</td>
      <td>${money(row.exit_price)}</td>
      <td>${pct(row.pnl_pct)}</td>
      <td>${row.exit_reason || "-"}</td>
      <td>${row.review_notes || ""}</td>
    </tr>
  `, "No closed ultra-short paper trades.");

  setRows("recentMarks", marks.recent_marks, row => `
    <tr>
      <td>${row.marked_at || "-"}</td>
      <td>${row.ticker || "-"}</td>
      <td>${row.contract_symbol || "-"}</td>
      <td>${money(row.current_price)}</td>
      <td>${pct(row.pnl_pct)}</td>
      <td>${row.signal || "-"}</td>
      <td>${row.reason || "-"}</td>
    </tr>
  `, "No ultra-short marks have been recorded.");

  document.getElementById("closedTradeCount").textContent = fmt(analytics.win_loss?.closed_trades, 0);
  document.getElementById("winRate").textContent = pct(analytics.win_loss?.win_rate);
  document.getElementById("totalPnl").textContent = money(analytics.win_loss?.total_pnl);
  document.getElementById("rejectedSetups").textContent = fmt(analytics.rejections?.rejected_setups, 0);
}

async function refreshUltraShortPortal(source = "manual") {
  if (ultraShortRefreshInProgress) return;
  const refreshButton = document.getElementById("refreshUltraShort");
  const refreshStatus = document.getElementById("ultraShortRefreshStatus");
  ultraShortRefreshInProgress = true;
  refreshButton.disabled = true;
  refreshStatus.textContent = source === "auto" ? "Auto refresh running..." : "Refresh running...";
  try {
    await loadUltraShortPortal();
    refreshStatus.textContent = `Last ${source} refresh: ${new Date().toLocaleString()} | Auto every ${ULTRA_SHORT_AUTO_REFRESH_LABEL}`;
  } catch (error) {
    refreshStatus.textContent = `Refresh failed: ${new Date().toLocaleString()} | Auto every ${ULTRA_SHORT_AUTO_REFRESH_LABEL}`;
    document.getElementById("ultraShortStatus").textContent = error.message;
    throw error;
  } finally {
    ultraShortRefreshInProgress = false;
    refreshButton.disabled = false;
  }
}

async function approveUltraShortCandidate(id, entryPrice) {
  const reviewNotes = window.prompt("Review notes", "Entry trigger, invalidation, stop, and time rule validated.");
  if (!reviewNotes || !reviewNotes.trim()) return;
  await fetchUltraShortJson(`/api/ultra-short/candidates/${id}/approve`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      entry_price: entryPrice > 0 ? entryPrice : null,
      review_notes: reviewNotes.trim()
    })
  });
  await loadUltraShortPortal();
}

async function rejectUltraShortCandidate(id) {
  const reason = window.prompt("Reject reason", "manual_reject");
  if (!reason) return;
  await fetchUltraShortJson(`/api/ultra-short/candidates/${id}/reject`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      reason: reason.trim() || "manual_reject",
      review_notes: `Rejected during manual review: ${reason.trim() || "manual_reject"}`
    })
  });
  await loadUltraShortPortal();
}

document.getElementById("refreshUltraShort").addEventListener("click", () => {
  refreshUltraShortPortal("manual").catch(error => console.error(error));
});

document.getElementById("exportUltraShort").addEventListener("click", () => {
  fetchUltraShortJson("/api/ultra-short/exports", {method: "POST"})
    .then(result => {
      document.getElementById("ultraShortStatus").textContent = `Exports saved: ${Object.values(result.paths || {}).join(", ")}`;
    })
    .catch(error => {
      document.getElementById("ultraShortStatus").textContent = error.message;
    });
});

refreshUltraShortPortal("initial").catch(error => console.error(error));
setInterval(() => {
  refreshUltraShortPortal("auto").catch(error => console.error(error));
}, ULTRA_SHORT_AUTO_REFRESH_MS);
