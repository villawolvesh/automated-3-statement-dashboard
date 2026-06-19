/* ===========================================================================
   Dashboard interactivity (financial-platform pattern).

   Each statement tab (Income / Balance / Cash Flow) is a spreadsheet table with
   ALL periods as columns and a sticky first column. Two toggles redraw it:
     View   : Values $ | Growth (YoY %) | % of Revenue/Assets
     Period : Annual | Quarterly  (quarterly = standalone quarters as filed;
              lines/quarters not filed standalone show "n/a" -- never derived)
   Clicking a row charts that line's trend. Bridges/5-year charts sit below as
   support. The Variance tab keeps the explicit Period A vs Period B comparator.
   Every number comes from the SQL views baked into DATA at build time.
   =========================================================================== */

const COL = {
  navy:'#1b2a4a', accent:'#2b6cb0', accent2:'#0e7490', muted:'#94a3b8',
  pos:'#15803d', neg:'#b91c1c', grid:'#eef2f7'
};
const CONFIG = { responsive:true, displayModeBar:false };

/* ----------------------------- formatters ------------------------------- */
const bil = v => v / 1e9;
function moneyB(b){
  const s = b < 0 ? '-' : '';
  return s + '$' + Math.abs(b).toLocaleString('en-US',
    {minimumFractionDigits:1, maximumFractionDigits:1}) + 'B';
}
function pct1(f){ return (f*100).toLocaleString('en-US',
  {minimumFractionDigits:1, maximumFractionDigits:1}) + '%'; }
function pct0(f){ return Math.round(f*100).toLocaleString('en-US') + '%'; }
function ratio2(v){ return v.toLocaleString('en-US',
  {minimumFractionDigits:2, maximumFractionDigits:2}); }

const YEARS = DATA.years;                 // [2021..2025]
const YL = YEARS.map(y => 'FY' + y);
const LAST = YEARS[YEARS.length - 1];     // latest fiscal year

/* ------------------------- shared Plotly layout ------------------------- */
function layout(extra){
  return Object.assign({
    font:{family:'-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif', size:12, color:'#334155'},
    margin:{l:58, r:18, t:12, b:40},
    paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
    colorway:[COL.accent, COL.navy, COL.accent2, COL.muted],
    hovermode:'closest', bargap:0.30,
    legend:{orientation:'h', y:1.13, x:0, font:{size:11}},
    xaxis:{gridcolor:COL.grid, zeroline:false, automargin:true},
    yaxis:{gridcolor:COL.grid, zeroline:false, automargin:true}
  }, extra || {});
}
function plot(id, traces, lay){
  Plotly.newPlot(id, traces, lay, CONFIG);
  document.getElementById(id).dataset.drawn = '1';
}
const M = y => DATA.metrics[y];

/* ===================== SPREADSHEET STATEMENT TABLES ===================== */
const STMT_TITLE = {income:'Income Statement', balance:'Balance Sheet', cashflow:'Cash Flow'};
const VIEW = {income:'values', balance:'values', cashflow:'values'};
const FREQ = {income:'annual', balance:'annual', cashflow:'annual'};
const SEL  = {income:null, balance:null, cashflow:null};   // selected row (line)
const QYEAR = {income:'last12', balance:'last12', cashflow:'last12'};   // quarterly year filter

function blockOf(tab){ return DATA.statements[tab][FREQ[tab]]; }

// Which period columns to show: all years (annual), or last-12 / one fiscal year (quarterly).
function visiblePeriods(tab){
  const all = blockOf(tab).periods;
  if(FREQ[tab] === 'annual') return all;
  if(QYEAR[tab] === 'last12') return all.slice(-12);
  return all.filter(p => p.fy === +QYEAR[tab]);
}
// A quarter is DERIVED (from YTD) for income Q4 and for cash-flow Q2-Q4; balance never.
function isDerived(tab, period){
  if(FREQ[tab] !== 'quarterly' || !period) return false;
  if(tab === 'income')   return period.q === 4;
  if(tab === 'cashflow') return period.q >= 2;
  return false;
}
const DERIV_TIP = 'Standalone quarter derived from year-to-date filings (Q1+Q2+Q3+Q4 = reported annual).';

function cellByView(tab, line, valmap, period, view, baseS){
  const v = valmap[line][period.key];
  let content;
  if(view === 'values'){
    content = v==null ? '<span class="naq">n/a</span>' : moneyB(bil(v));
  } else if(view === 'growth' || view === 'growthq'){
    const pk = view === 'growth' ? period.prev : period.prevSeq;   // YoY vs QoQ
    const vp = pk!=null ? valmap[line][pk] : null;
    if(v==null || vp==null || vp===0){ content = '<span class="naq">–</span>'; }
    else { const g=(v-vp)/Math.abs(vp); const cls=g>=0?'pos':'neg';
           content = '<span class="chip '+cls+'">'+(g>=0?'+':'')+pct1(g)+'</span>'; }
  } else {
    const base = baseS ? baseS[period.key] : null;
    content = (v==null||base==null||base===0) ? '<span class="naq">–</span>' : pct1(v/base);
  }
  return content + cellMarkers(tab, line, period);
}

/* ----------- variance markers (auto flags + curated notes) ------------- */
const NOTABLE = {};   // tab -> {annual:{"line|key":text}, quarterly:{...}}
function buildNotable(){
  ['income','balance','cashflow'].forEach(tab=>{
    NOTABLE[tab] = {annual:{}, quarterly:{}};
    ['annual','quarterly'].forEach(mode=>{
      ((DATA.notable[tab]||{})[mode]||[]).forEach(it=>{ NOTABLE[tab][mode][it.line+'|'+it.periodKey] = it.text; });
    });
  });
}
function escAttr(s){ return s.replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;'); }
function cellMarkers(tab, line, period){
  let mk = '';
  const nm = NOTABLE[tab] && NOTABLE[tab][FREQ[tab]];     // undefined for ratios tab
  const at = nm && nm[line+'|'+period.key];
  if(at) mk += '<span class="cellflag" title="'+escAttr(at)+'"></span>';
  const cur = DATA.curated[tab+'|'+line+'|'+period.label];
  if(cur){
    const tip = cur.explanation + (cur.source_url ? '  (source: '+cur.source_url+')' : '');
    mk += '<span class="cellnote" title="'+escAttr(tip)+'">&#9432;</span>';
  }
  const rev = DATA.revisions && DATA.revisions[tab+'|'+line+'|'+period.label];
  if(rev){
    const tip = 'Revised from '+moneyB(bil(rev.old))+' to '+moneyB(bil(rev.new))+' on '+rev.date;
    mk += '<span class="cellrev" title="'+escAttr(tip)+'">&#8635;</span>';
  }
  return mk;
}
function renderNotable(tab){
  // Only notes whose period is currently in view (mode + year filter).
  const visKeys = new Set(visiblePeriods(tab).map(p=>p.key));
  const visLabels = new Set(visiblePeriods(tab).map(p=>p.label));
  const items = ((DATA.notable[tab]||{})[FREQ[tab]]||[]).filter(it=>visKeys.has(it.periodKey));
  const curated = Object.keys(DATA.curated).filter(k=>{
    const p = k.split('|'); return p[0]===tab && visLabels.has(p[2]);
  });
  const box = document.getElementById('notable-'+tab);
  if(!items.length && !curated.length){ box.innerHTML=''; return; }
  let h = '<div class="nhead">Notable items — auto-detected magnitude &middot; '+
          '<span style="color:#b07d18;">&#9432; verified notes</span></div>';
  items.forEach(it=>{ h += '<div class="nitem">'+it.text+'</div>'; });
  curated.forEach(k=>{
    const p = k.split('|'), c = DATA.curated[k];
    h += '<div class="nitem curated"><b>'+p[1]+' · '+p[2]+':</b> '+c.explanation +
         (c.source_url ? ' <a class="src" href="'+c.source_url+'" target="_blank" rel="noopener">source &#8599;</a>' : '') +
         '</div>';
  });
  box.innerHTML = h;
}

/* ------------------------ single-period bridges ------------------------ */
function drawIncomeBridge(d){
  const x = ['Revenue','Cost of Revenue','Gross Profit','Operating Exp.','Operating Income','Taxes & Other','Net Income'];
  const measure = ['absolute','relative','total','relative','total','relative','total'];
  const y = [d.rev, -d.cogs, d.gp, -d.opex, d.oi, d.ni - d.oi, d.ni].map(bil);
  plot('c-income-waterfall', [{
    type:'waterfall', x, measure, y, text:y.map(moneyB), textposition:'outside',
    increasing:{marker:{color:COL.accent}}, decreasing:{marker:{color:COL.neg}},
    totals:{marker:{color:COL.navy}}, connector:{line:{color:COL.muted, width:1}},
    hovertemplate:'%{x}: %{text}<extra></extra>'
  }], layout({yaxis:{ticksuffix:'B', tickprefix:'$'}, margin:{l:55,r:12,t:12,b:48}}));
}
function drawCashBridge(d){
  const x = ['Beginning','Operating','Investing','Financing','Ending'];
  const measure = ['absolute','relative','relative','relative','total'];
  const y = [d.beg, d.cfo, d.cfi, d.cff, d.end].map(bil);
  plot('c-cash-waterfall', [{
    type:'waterfall', x, measure, y, text:y.map(moneyB), textposition:'outside',
    increasing:{marker:{color:COL.accent}}, decreasing:{marker:{color:COL.neg}},
    totals:{marker:{color:COL.navy}}, connector:{line:{color:COL.muted, width:1}},
    hovertemplate:'%{x}: %{text}<extra></extra>'
  }], layout({yaxis:{ticksuffix:'B', tickprefix:'$'}, margin:{l:55,r:12,t:12,b:40}}));
}
const BRIDGE = { income:{key:'income', title:'Income bridge — Revenue to Net Income', draw:drawIncomeBridge},
                 cashflow:{key:'cash', title:'Cash bridge — Beginning to Ending cash', draw:drawCashBridge} };
function populateBridgeSel(tab){
  const cfg = BRIDGE[tab], freq = FREQ[tab];
  const avail = DATA.bridges[cfg.key][freq==='annual'?'annual':'quarterly'];
  const periods = visiblePeriods(tab).filter(p=>avail[p.key] != null);
  const sel = document.getElementById(tab+'-bridge-sel');
  sel.innerHTML = '';
  periods.forEach(p=> sel.add(new Option(p.label, p.key)));
  if(periods.length) sel.value = periods[periods.length-1].key;   // latest available
  sel.onchange = ()=> drawBridge(tab);
}
function drawBridge(tab){
  const cfg = BRIDGE[tab], freq = FREQ[tab];
  const sel = document.getElementById(tab+'-bridge-sel');
  const avail = DATA.bridges[cfg.key][freq==='annual'?'annual':'quarterly'];
  const key = sel.value;
  const period = key ? blockOf(tab).periods.find(p=>p.key===key) : null;
  const d = period ? avail[key] : null;
  const deriv = isDerived(tab, period)
    ? '<span class="derivtag" title="'+escAttr(DERIV_TIP)+'">derived from YTD</span>' : '';
  document.getElementById(tab+'-bridge-title').innerHTML =
    cfg.title + (period ? ' ('+period.label+')' : '') + deriv;
  if(d) cfg.draw(d);
}

function renderSheet(tab){
  const blk = blockOf(tab), view = VIEW[tab];
  const periods = visiblePeriods(tab), baseS = blk.base_series;
  const valmap = {}; blk.rows.forEach(r=>{ valmap[r.line] = r.values; });
  if(SEL[tab] == null && blk.rows.length) SEL[tab] = blk.rows[0].line;

  let h = '<table class="sheet"><thead><tr><th>'+STMT_TITLE[tab]+'</th>';
  periods.forEach(p=>{
    const d = isDerived(tab, p) ? '<span class="cellderiv" title="'+escAttr(DERIV_TIP)+'">d</span>' : '';
    h += '<th>'+p.label+d+'</th>';
  });
  h += '</tr></thead><tbody>';
  blk.rows.forEach((r, i)=>{
    const selCls = (r.line===SEL[tab]) ? ' sel' : '';
    h += '<tr class="clickable'+selCls+'" data-idx="'+i+'"><td>'+r.line+'</td>';
    periods.forEach(p=>{ h += '<td>'+cellByView(tab, r.line, valmap, p, view, baseS)+'</td>'; });
    h += '</tr>';
  });
  h += '</tbody></table>';
  document.getElementById('t-'+tab+'-sheet').innerHTML = h;

  // wire row clicks -> trend
  document.querySelectorAll('#t-'+tab+'-sheet tr.clickable').forEach(tr=>{
    tr.onclick = ()=>{
      SEL[tab] = blk.rows[+tr.dataset.idx].line;
      document.querySelectorAll('#t-'+tab+'-sheet tr').forEach(x=>x.classList.remove('sel'));
      tr.classList.add('sel');
      drawRowTrend(tab);
    };
  });

  // quarterly coverage note
  const qn = document.getElementById('qnote-'+tab);
  if(FREQ[tab]==='quarterly'){
    let msg = '<b>Quarterly note:</b> Apple files figures year-to-date and no standalone '+
      'fiscal Q4. Columns marked <span class="cellderiv">d</span> are standalone quarters '+
      'derived by differencing YTD filings (income Q4; cash-flow Q2&ndash;Q4) and reconcile '+
      'exactly to the reported annual. Balance-sheet items are quarter-end snapshots (not derived).';
    if(PARTIAL.has(QYEAR[tab])){
      msg += ' <b style="color:#b07d18;">FY'+QYEAR[tab]+' is in progress</b> — only the filed '+
        'quarters are shown (year-to-date); it is not a complete fiscal year and is never '+
        'used as a full-year comparison base.';
    }
    qn.innerHTML = msg;
  } else { qn.textContent = ''; }

  // view subtitle (what the current view compares against)
  const base = tab==='balance' ? 'total assets' : 'revenue';
  const SUB = {
    values: 'Values in USD billions.',
    growth: 'YoY — vs the same period last year (Annual: prior fiscal year; Quarterly: same quarter last year).',
    growthq:'QoQ — vs the immediately prior period (Quarterly: prior quarter; Annual: same as YoY).',
    pct: 'Each line as % of ' + base + ' for its period.'
  };
  document.getElementById('viewsub-'+tab).textContent = SUB[view];

  renderNotable(tab);   // notes follow the visible periods + mode
}

function drawRowTrend(tab){
  const blk = blockOf(tab), line = SEL[tab];
  const row = blk.rows.find(r=>r.line===line);
  const periods = visiblePeriods(tab);
  const xs = periods.map(p=>p.label);
  const ys = periods.map(p=>{ const v=row.values[p.key]; return v==null?null:bil(v); });
  document.getElementById('rowtitle-'+tab).textContent =
    line + ' — ' + (FREQ[tab]==='annual'?'annual':'quarterly') + ' trend';
  plot('c-'+tab+'-rowtrend', [{
    type:'scatter', mode:'lines+markers', x:xs, y:ys, connectgaps:false,
    line:{color:COL.accent, width:2.5}, marker:{size:7},
    hovertemplate:'%{x}: $%{y:.1f}B<extra></extra>'
  }], layout({yaxis:{ticksuffix:'B', tickprefix:'$'}, showlegend:false}));
}

/* toggle handling (event-delegated in init) */
function setToggle(tab, group, value){
  if(group==='view') VIEW[tab] = value; else FREQ[tab] = value;
  if(group==='freq'){ SEL[tab] = null; toggleYearSel(tab); }   // periods changed -> reset
  renderSheet(tab);
  if(group==='freq'){
    drawRowTrend(tab);
    if(BRIDGE[tab]){ populateBridgeSel(tab); drawBridge(tab); }   // bridge follows period mode
  }
}
function toggleYearSel(tab){
  const show = FREQ[tab] === 'quarterly';
  document.querySelectorAll('[data-yeartab="'+tab+'"]').forEach(e=>{ e.style.display = show ? '' : 'none'; });
}
function onYearChange(tab, value){
  QYEAR[tab] = value;
  SEL[tab] = null;
  renderSheet(tab); drawRowTrend(tab);
  if(BRIDGE[tab]){ populateBridgeSel(tab); drawBridge(tab); }
}
const PARTIAL = new Set((DATA.quarter_partial||[]).map(String));
function populateYearSel(tab){
  const sel = document.getElementById(tab+'-year-sel');
  sel.innerHTML = '';
  sel.add(new Option('Last 12 quarters', 'last12'));
  (DATA.quarter_years||[]).forEach(y=>{
    const lbl = 'FY'+y + (PARTIAL.has(String(y)) ? ' (partial · YTD)' : '');
    sel.add(new Option(lbl, String(y)));
  });
  sel.value = QYEAR[tab];
  sel.onchange = ()=> onYearChange(tab, sel.value);
}

/* =============================== INCOME ================================= */
function drawIncome(){
  renderSheet('income'); drawRowTrend('income');
  populateBridgeSel('income'); drawBridge('income');

  plot('c-income-trend', [
    {type:'bar', name:'Revenue', x:YL, y:YEARS.map(y=>bil(M(y).revenue)), marker:{color:COL.accent}},
    {type:'bar', name:'Net Income', x:YL, y:YEARS.map(y=>bil(M(y).net_income)), marker:{color:COL.navy}},
    {type:'scatter', name:'Net margin', mode:'lines+markers', x:YL,
     y:YEARS.map(y=>DATA.ratios[y].net_margin*100), yaxis:'y2', line:{color:COL.accent2, width:2.5}}
  ], layout({barmode:'group', margin:{l:58, r:52, t:30, b:40},
     yaxis:{ticksuffix:'B', tickprefix:'$'},
     yaxis2:{overlaying:'y', side:'right', ticksuffix:'%', showgrid:false, rangemode:'tozero'}}));
}

/* =============================== BALANCE ================================ */
function drawBalance(){
  renderSheet('balance'); drawRowTrend('balance');
  const assets = YEARS.map(y=>bil(M(y).total_assets));
  const liab   = YEARS.map(y=>bil(M(y).total_liabilities));
  const eq     = YEARS.map(y=>bil(M(y).total_equity));
  plot('c-balance-identity', [
    {type:'bar', name:'Total Assets', x:YL, y:assets, offsetgroup:'a', marker:{color:COL.navy}},
    {type:'bar', name:'Total Liabilities', x:YL, y:liab, offsetgroup:'b', marker:{color:COL.accent}},
    {type:'bar', name:'Total Equity', x:YL, y:eq, offsetgroup:'b', base:liab, marker:{color:COL.accent2}}
  ], layout({barmode:'group', yaxis:{ticksuffix:'B', tickprefix:'$'}}));

  plot('c-balance-trend', [
    {type:'scatter', mode:'lines+markers', name:'Total Equity', x:YL, y:eq, line:{color:COL.accent2, width:2.5}},
    {type:'scatter', mode:'lines+markers', name:'Cash & Equiv.', x:YL,
     y:YEARS.map(y=>bil(M(y).cash)), line:{color:COL.accent, width:2.5}}
  ], layout({yaxis:{ticksuffix:'B', tickprefix:'$'}}));
}

/* ============================== CASH FLOW ============================== */
function drawCashflow(){
  renderSheet('cashflow'); drawRowTrend('cashflow');
  populateBridgeSel('cashflow'); drawBridge('cashflow');

  plot('c-cash-fcf', [
    {type:'bar', name:'Operating CF', x:YL, y:YEARS.map(y=>bil(M(y).operating_cf)), marker:{color:COL.accent}},
    {type:'bar', name:'CapEx', x:YL, y:YEARS.map(y=>bil(M(y).capex)), marker:{color:COL.muted}},
    {type:'scatter', name:'Free Cash Flow', mode:'lines+markers', x:YL,
     y:YEARS.map(y=>bil(M(y).operating_cf - M(y).capex)), line:{color:COL.navy, width:2.5}}
  ], layout({barmode:'group', yaxis:{ticksuffix:'B', tickprefix:'$'}}));

  plot('c-cash-activities', [
    {type:'bar', name:'Operating', x:YL, y:YEARS.map(y=>bil(M(y).operating_cf)), marker:{color:COL.accent}},
    {type:'bar', name:'Investing', x:YL, y:YEARS.map(y=>bil(M(y).investing_cf)), marker:{color:COL.accent2}},
    {type:'bar', name:'Financing', x:YL, y:YEARS.map(y=>bil(M(y).financing_cf)), marker:{color:COL.navy}}
  ], layout({barmode:'group', yaxis:{ticksuffix:'B', tickprefix:'$'}}));
}

/* =============================== RATIOS ================================ */
function fmtRatio(v, fmt){
  if(v==null) return '<span class="naq">–</span>';
  if(fmt==='pct') return pct1(v);
  if(fmt==='x')   return ratio2(v);
  return moneyB(bil(v));            // money
}
function drawRatios(){
  const r = DATA.ratios[LAST], prevY = YEARS[YEARS.length-2], rc = DATA.ratios[prevY];
  const fcf = M(LAST).operating_cf - M(LAST).capex, fcfC = M(prevY).operating_cf - M(prevY).capex;
  const ppRoe=(r.roe-rc.roe)*100, ppNm=(r.net_margin-rc.net_margin)*100;
  const dCr=r.current_ratio-rc.current_ratio, pFcf=fcfC?(fcf-fcfC)/Math.abs(fcfC):null;
  document.getElementById('kpi-ratios').innerHTML =
    kpi('Return on Equity', pct0(r.roe), chgPP(ppRoe,0,prevY)) +
    kpi('Net Margin', pct1(r.net_margin), chgPP(ppNm,1,prevY)) +
    kpi('Current Ratio', ratio2(r.current_ratio), chgAbs(dCr,prevY)) +
    kpi('Free Cash Flow', moneyB(bil(fcf)), chgPct(pFcf,prevY));

  // ratios table (all years)
  const rt = DATA.ratios_table;
  let h = '<table class="sheet"><thead><tr><th>Ratio</th>';
  rt.periods.forEach(p=>{ h += '<th>'+p.label+'</th>'; });
  h += '</tr></thead><tbody>';
  rt.rows.forEach(row=>{
    h += '<tr><td>'+row.label+'</td>';
    rt.periods.forEach(p=>{
      h += '<td>'+fmtRatio(row.values[p.key], row.fmt)+cellMarkers('ratios', row.label, p)+'</td>';
    });
    h += '</tr>';
  });
  document.getElementById('t-ratios-sheet').innerHTML = h + '</tbody></table>';

  plot('c-ratios-margins', [
    {type:'scatter', mode:'lines+markers', name:'Gross margin', x:YL, y:YEARS.map(y=>DATA.ratios[y].gross_margin*100), line:{color:COL.accent, width:2.5}},
    {type:'scatter', mode:'lines+markers', name:'Operating margin', x:YL, y:YEARS.map(y=>DATA.ratios[y].operating_margin*100), line:{color:COL.accent2, width:2.5}},
    {type:'scatter', mode:'lines+markers', name:'Net margin', x:YL, y:YEARS.map(y=>DATA.ratios[y].net_margin*100), line:{color:COL.navy, width:2.5}}
  ], layout({yaxis:{ticksuffix:'%'}}));

  plot('c-ratios-roe', [{
    type:'scatter', mode:'lines+markers', name:'ROE', x:YL,
    y:YEARS.map(y=>DATA.ratios[y].roe*100), line:{color:COL.navy, width:2.5},
    fill:'tozeroy', fillcolor:'rgba(43,108,176,0.08)'
  }], layout({yaxis:{ticksuffix:'%'}, showlegend:false}));

  plot('c-ratios-liquidity', [
    {type:'bar', name:'Free Cash Flow', x:YL, y:YEARS.map(y=>bil(M(y).operating_cf - M(y).capex)), marker:{color:COL.accent}},
    {type:'scatter', name:'Current ratio', mode:'lines+markers', x:YL, y:YEARS.map(y=>DATA.ratios[y].current_ratio), yaxis:'y2', line:{color:COL.navy, width:2.5}}
  ], layout({yaxis:{ticksuffix:'B', tickprefix:'$'}, yaxis2:{overlaying:'y', side:'right', showgrid:false, rangemode:'tozero'}}));
}
function kpi(label, val, chg){
  return '<div class="kpi"><div class="k-label">'+label+'</div>' +
         '<div class="k-val">'+val+'</div>' +
         '<div class="k-chg '+chg.cls+'">'+chg.text+'</div></div>';
}
function chgSign(x){ return x>=0 ? 'pos' : 'neg'; }
function chgPP(pp, dec, comp){ return {text:(pp>=0?'+':'')+pp.toFixed(dec)+' pp vs FY'+comp, cls:chgSign(pp)}; }
function chgAbs(d, comp){ return {text:(d>=0?'+':'')+d.toFixed(2)+' vs FY'+comp, cls:chgSign(d)}; }
function chgPct(p, comp){ return p==null ? {text:'vs FY'+comp, cls:''}
                          : {text:(p>=0?'+':'')+pct1(p)+' vs FY'+comp, cls:chgSign(p)}; }

/* ============================== VARIANCE =============================== */
const getBase    = () => +document.getElementById('sel-base').value;
const getCompare = () => +document.getElementById('sel-compare').value;
const mval = (y, key) => key === 'fcf' ? (M(y).operating_cf - M(y).capex) : M(y)[key];
const VAR_METRICS = [
  ['Revenue','revenue'], ['Gross Profit','gross_profit'], ['Operating Income','operating_income'],
  ['Net Income','net_income'], ['Total Assets','total_assets'], ['Total Equity','total_equity'],
  ['Operating Cash Flow','operating_cf'], ['Free Cash Flow','fcf']
];
function drawVariance(){
  const base = getBase(), comp = getCompare();
  const rows = VAR_METRICS.map(([label,key])=>{
    const b=mval(base,key), c=mval(comp,key), d=b-c, p=c!==0?d/Math.abs(c):null;
    return {label,b,c,d,p};
  });
  let h = '<table class="fin"><thead><tr><th>Metric</th><th>FY'+base+'</th><th>FY'+comp+
          '</th><th>&Delta;</th><th>&Delta; %</th></tr></thead><tbody>';
  rows.forEach(r=>{
    const cls=r.d>=0?'pos':'neg', pstr=r.p==null?'–':((r.p>=0?'+':'')+pct1(r.p));
    h += '<tr><td>'+r.label+'</td><td>'+moneyB(bil(r.b))+'</td><td>'+moneyB(bil(r.c))+'</td>'+
         '<td class="'+cls+'">'+(r.d>=0?'+':'')+moneyB(bil(r.d))+'</td>'+
         '<td><span class="chip '+cls+'">'+pstr+'</span></td></tr>';
  });
  document.getElementById('t-variance').innerHTML = h + '</tbody></table>';

  const t = rows.filter(r=>r.p!=null).slice().sort((a,b)=>a.p-b.p);
  const tmax = Math.max(...t.map(r=>Math.abs(r.p*100)));
  plot('c-variance-tornado', [{
    type:'bar', orientation:'h', x:t.map(r=>r.p*100), y:t.map(r=>r.label),
    marker:{color:t.map(r=>r.p>=0?COL.pos:COL.neg)},
    text:t.map(r=>(r.p>=0?'+':'')+pct1(r.p)),
    textposition:t.map(r=>r.p>=0?'outside':'inside'), insidetextanchor:'end',
    textfont:{size:11}, cliponaxis:false,
    hovertemplate:'%{y}: %{text}<extra></extra>'
  }], layout({xaxis:{ticksuffix:'%', zeroline:true, zerolinecolor:COL.muted,
       gridcolor:COL.grid, range:[-tmax*1.25, tmax*1.3]},
       margin:{l:170, r:48, t:10, b:30}, showlegend:false}));

  const sorted = rows.filter(r=>r.p!=null).slice().sort((a,b)=>Math.abs(b.p)-Math.abs(a.p));
  const top = sorted[0];
  const bps = Math.round((DATA.ratios[base].net_margin - DATA.ratios[comp].net_margin)*10000);
  document.getElementById('ins-variance').innerHTML =
    'Largest move <b>FY'+base+'</b> vs <b>FY'+comp+'</b>: <b>'+top.label+'</b> '+
    (top.p>=0?'+':'')+pct1(top.p)+'. Net margin '+(bps>=0?'expanded':'compressed')+' '+
    Math.abs(bps)+' bps to '+pct1(DATA.ratios[base].net_margin)+'.';
}

/* ----------------------------- navigation ------------------------------ */
const DRAWERS = { income:drawIncome, balance:drawBalance, cashflow:drawCashflow, ratios:drawRatios, variance:drawVariance };
const drawn = {};

function showTab(name){
  document.querySelectorAll('.tab-btn').forEach(b=>b.classList.toggle('active', b.dataset.tab===name));
  document.querySelectorAll('.panel').forEach(p=>p.classList.toggle('active', p.id==='tab-'+name));
  if(!drawn[name]){ DRAWERS[name](); drawn[name] = true; }
  resizePanel(name);
}
function resizePanel(name){
  document.querySelectorAll('#tab-'+name+' .chart').forEach(d=>{ if(d.dataset.drawn) Plotly.Plots.resize(d); });
}
function updateYearLabels(){
  document.querySelectorAll('.yr-base').forEach(e=>e.textContent='FY'+getBase());
  document.querySelectorAll('.yr-comp').forEach(e=>e.textContent='FY'+getCompare());
}
function onPeriodChange(){ updateYearLabels(); drawVariance(); }

/* -------------------------------- init --------------------------------- */
function init(){
  buildNotable();
  const desc = YEARS.slice().sort((a,b)=>b-a);
  const baseSel = document.getElementById('sel-base');
  const compSel = document.getElementById('sel-compare');
  desc.forEach(y=>{ baseSel.add(new Option('FY'+y, y)); compSel.add(new Option('FY'+y, y)); });
  baseSel.value = desc[0]; compSel.value = desc[1];
  baseSel.onchange = onPeriodChange; compSel.onchange = onPeriodChange;

  document.querySelectorAll('.tab-btn').forEach(b=>b.onclick=()=>showTab(b.dataset.tab));

  ['income','balance','cashflow'].forEach(populateYearSel);   // quarterly year filters

  // toggle buttons (view / frequency)
  document.querySelectorAll('.toggle').forEach(grp=>{
    const tab = grp.dataset.tab, group = grp.dataset.group;
    grp.querySelectorAll('button').forEach(btn=>{
      btn.onclick = ()=>{
        grp.querySelectorAll('button').forEach(b=>b.classList.remove('active'));
        btn.classList.add('active');
        setToggle(tab, group, group==='view' ? btn.dataset.v : btn.dataset.f);
      };
    });
  });

  // blue insights (latest fiscal year) + analyst notes
  document.getElementById('ins-income').innerHTML   = INSIGHTS.income;
  document.getElementById('ins-balance').innerHTML  = INSIGHTS.balance;
  document.getElementById('ins-cashflow').innerHTML = INSIGHTS.cashflow;
  document.getElementById('ins-ratios').innerHTML   = INSIGHTS.ratios;
  [['note-income','income_note'], ['note-ratios','ratios_note'], ['note-cashflow','cashflow_note']]
    .forEach(function(pair){
      const el = document.getElementById(pair[0]), txt = INSIGHTS[pair[1]];
      if(el){ if(txt){ el.innerHTML = txt; } else { el.style.display='none'; } }
    });

  updateYearLabels();
  showTab('income');

  window.addEventListener('resize', ()=>{
    document.querySelectorAll('.chart').forEach(d=>{ if(d.dataset.drawn) Plotly.Plots.resize(d); });
  });
}
init();
