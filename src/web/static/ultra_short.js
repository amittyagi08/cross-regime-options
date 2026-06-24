async function fetchUltraShortJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} failed with ${response.status}`);
  return response.json();
}

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

async function loadUltraShortPortal() {
  const snapshot = await fetchUltraShortJson("/api/ultra-short/snapshot");
  document.getElementById("ultraShortStatus").textContent = snapshot.warning || "Portal shell";
  document.getElementById("labMode").textContent = snapshot.mode || "-";
  document.getElementById("labAsOf").textContent = snapshot.as_of || "-";
  document.getElementById("marketMode").textContent = snapshot.market_bias?.mode || "-";
  document.getElementById("nextPhase").textContent = snapshot.implementation_phase?.next || "-";
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
  `, "Intraday sector scoring will appear in Phase 2.");

  const setupRenderer = row => `
    <tr>
      <td>${row.ticker || "-"}</td>
      <td>${row.contract_symbol || "-"}</td>
      <td>${row.expiry || "-"}</td>
      <td>${money(row.suggested_premium)}</td>
      <td>${fmt(row.delta)}</td>
      <td>${pct(row.spread_pct)}</td>
      <td>${fmt(row.dte, 0)}</td>
      <td>${row.setup_state || "-"}</td>
      <td>${row.entry_trigger || "-"}</td>
      <td>${fmt(row.ultra_short_score)}</td>
      <td><button class="score-button" type="button" disabled>Review</button></td>
    </tr>
  `;
  setRows("callSetups", snapshot.call_setups, setupRenderer, "Call setup candidates will appear after the ultra-short snapshot service is connected.");
  setRows("putSetups", snapshot.put_setups, setupRenderer, "Put setup candidates will appear after the ultra-short snapshot service is connected.");

  setRows("activeTrades", snapshot.active_trades, row => `
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

  setRows("closedTrades", snapshot.closed_trades, row => `
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

  setRows("recentMarks", snapshot.recent_marks, row => `
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
}

document.getElementById("refreshUltraShort").addEventListener("click", () => {
  loadUltraShortPortal().catch(error => {
    document.getElementById("ultraShortStatus").textContent = error.message;
  });
});

loadUltraShortPortal().catch(error => {
  document.getElementById("ultraShortStatus").textContent = error.message;
});
