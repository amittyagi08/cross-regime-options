async function fetchDayTradingJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} failed with ${response.status}`);
  return response.json();
}

const DAY_TRADING_AUTO_REFRESH_MS = 5 * 60 * 1000;
let dayTradingRefreshInProgress = false;

function fmt(value, digits = 2) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") return value.toFixed(digits);
  return value;
}

function pct(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function money(value) {
  if (value === null || value === undefined || value === "") return "-";
  return `$${Number(value).toFixed(2)}`;
}

function setRows(id, rows, render, emptyText) {
  const body = document.getElementById(id);
  if (!rows || !rows.length) {
    body.innerHTML = `<tr><td colspan="13" class="empty-table">${emptyText}</td></tr>`;
    return;
  }
  body.innerHTML = rows.map(render).join("");
}

function statusClass(status) {
  if (["STRONG_LONG", "LONG_BIAS", "TRIGGERED"].includes(status)) return "status-allowed";
  if (["STRONG_SHORT", "SHORT_BIAS", "INVALIDATED"].includes(status)) return "status-blocked";
  return "status-neutral";
}

async function loadDayTradingDashboard() {
  const snapshot = await fetchDayTradingJson("/api/day-trading/snapshot");
  document.getElementById("dayTradingStatus").textContent = snapshot.warning || "Manual review only";
  document.getElementById("marketStatus").textContent = snapshot.market_status || "-";
  document.getElementById("marketScore").textContent = fmt(snapshot.market_score);
  document.getElementById("provider").textContent = snapshot.provider || "-";
  document.getElementById("asOf").textContent = snapshot.as_of || "-";
  document.getElementById("marketBanner").className = `market-banner ${statusClass(snapshot.market_status)}`;

  setRows("marketRows", snapshot.market_rows, row => `
    <tr>
      <td>${row.symbol || "-"}</td>
      <td><span class="status-pill ${statusClass(row.status)}">${row.status || "-"}</span></td>
      <td>${money(row.last_price)}</td>
      <td>${money(row.vwap)}</td>
      <td>${row.vwap_state || "-"}</td>
      <td>${pct(row.vwap_slope)}</td>
      <td>${row.pivot_position || "-"}</td>
      <td>${row.trend_structure || "-"}</td>
      <td>${pct(row.distance_from_vwap)}</td>
      <td>${fmt(row.score)}</td>
    </tr>
  `, "Market status will appear when intraday SPY/QQQ bars are available.");

  setRows("pivotRows", snapshot.pivot_map, row => `
    <tr>
      <td>${row.symbol || "-"}</td>
      <td>${money(row.last_price)}</td>
      <td>${money(row.pp)}</td>
      <td>${money(row.r1)}</td>
      <td>${money(row.r2)}</td>
      <td>${money(row.r3)}</td>
      <td>${money(row.s1)}</td>
      <td>${money(row.s2)}</td>
      <td>${money(row.s3)}</td>
      <td>${money(row.previous_high)}</td>
      <td>${money(row.previous_low)}</td>
      <td>${money(row.opening_range_high)}</td>
      <td>${money(row.opening_range_low)}</td>
    </tr>
  `, "Pivot levels need previous-session and opening-range bars.");

  const signalRenderer = row => `
    <tr>
      <td>${row.ticker || "-"}</td>
      <td>${row.direction || "-"}</td>
      <td>${row.setup || "-"}</td>
      <td>${row.market_confirmed ? "Yes" : "No"}</td>
      <td>${row.vwap_state || "-"}</td>
      <td>${row.pivot_level || "-"}</td>
      <td><span class="status-pill ${statusClass(row.signal_state)}">${fmt(row.score)}</span></td>
      <td>${row.entry_trigger || "-"}</td>
      <td>${row.stop || "-"}</td>
      <td>${row.target || "-"}</td>
      <td>${row.action || "-"}</td>
    </tr>
  `;
  setRows("longSetups", snapshot.long_setups, signalRenderer, "No long setups are available.");
  setRows("shortSetups", snapshot.short_setups, signalRenderer, "No short setups are available.");

  setRows("activeTrades", snapshot.active_trades, row => `
    <tr><td>${row.ticker || "-"}</td><td>${row.direction || "-"}</td><td>${money(row.entry)}</td><td>${money(row.stop)}</td><td>${money(row.target)}</td><td>${row.state || "-"}</td><td>${money(row.pnl)}</td></tr>
  `, "No active day trades.");
  setRows("closedTrades", snapshot.closed_trades, row => `
    <tr><td>${row.ticker || "-"}</td><td>${row.direction || "-"}</td><td>${money(row.entry)}</td><td>${money(row.exit)}</td><td>${money(row.pnl)}</td><td>${row.exit_reason || "-"}</td></tr>
  `, "No closed day trades.");

  const performance = snapshot.daily_performance || {};
  document.getElementById("realizedPnl").textContent = money(performance.realized_pnl);
  document.getElementById("openRisk").textContent = money(performance.open_risk);
  document.getElementById("tradesTaken").textContent = `${fmt(performance.trades_taken, 0)} / ${fmt(performance.max_trades_per_day, 0)}`;
  document.getElementById("dailyLossLimit").textContent = money(performance.daily_loss_limit);
}

async function refreshDayTradingDashboard(source = "manual") {
  if (dayTradingRefreshInProgress) return;
  const refreshButton = document.getElementById("refreshDayTrading");
  const refreshStatus = document.getElementById("dayTradingRefreshStatus");
  dayTradingRefreshInProgress = true;
  refreshButton.disabled = true;
  refreshStatus.textContent = source === "auto" ? "Auto refresh running..." : "Refresh running...";
  try {
    await loadDayTradingDashboard();
    refreshStatus.textContent = `Last ${source} refresh: ${new Date().toLocaleString()} | Auto every 5 minutes`;
  } catch (error) {
    refreshStatus.textContent = `Refresh failed: ${new Date().toLocaleString()} | Auto every 5 minutes`;
    document.getElementById("dayTradingStatus").textContent = error.message;
    throw error;
  } finally {
    dayTradingRefreshInProgress = false;
    refreshButton.disabled = false;
  }
}

document.getElementById("refreshDayTrading").addEventListener("click", () => {
  refreshDayTradingDashboard("manual").catch(error => console.error(error));
});

refreshDayTradingDashboard("initial").catch(error => console.error(error));
setInterval(() => {
  refreshDayTradingDashboard("auto").catch(error => console.error(error));
}, DAY_TRADING_AUTO_REFRESH_MS);
