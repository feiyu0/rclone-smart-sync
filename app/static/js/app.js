// app.js - 所有前端逻辑

// 全局变量
let cfg = {};
let logFilter = 'all';
let allLogs = [];
let monitorOn = false;
let syncOn = false;
let schedOn = false;

// ── 页面导航 ──────────────────────────────────────────────
function showPage(id, btn) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  if (btn) btn.classList.add('active');
  if (id === 'config') loadConfig();
}

// ── SSE 实时日志 ──────────────────────────────────────────
function startSSE() {
  const es = new EventSource('/api/stream');
  es.addEventListener('log', e => {
    const entry = JSON.parse(e.data);
    allLogs.push(entry);
    if (allLogs.length > 500) allLogs.shift();
    appendLog(entry);
  });
  es.addEventListener('status', e => {
    const d = JSON.parse(e.data);
    if (d.monitor_running !== undefined) updateMonitorUI(d.monitor_running);
  });
  es.onerror = () => setTimeout(startSSE, 3000);
}

// ── 状态轮询 ──────────────────────────────────────────────
function pollStatus() {
  fetch('/api/status').then(r => r.json()).then(d => {
    updateMonitorUI(d.monitor_running);
    updateSyncUI(d.sync_running, d.last_sync);
    updateMetrics(d.stats, d.queue, d.snapshot_age_hours);
    updateQueue(d.queue);
  }).catch(() => {});
}

function updateMonitorUI(on) {
  monitorOn = on;
  const togTrack = document.getElementById('tog-monitor');
  const togKnob = document.getElementById('knob-monitor');
  if (togTrack) togTrack.classList.toggle('on', on);
  if (togKnob) togKnob.classList.toggle('on', on);
  
  const badge = document.getElementById('badge-monitor');
  if (badge) {
    badge.textContent = on ? '运行中' : '未启动';
    badge.className = 'badge ' + (on ? 'badge-ok' : 'badge-muted');
  }
  
  const hdr = document.getElementById('hdr-monitor');
  if (hdr) {
    hdr.innerHTML = `<span class="dot ${on ? 'dot-on' : 'dot-off'}"></span>${on ? '监控运行中' : '监控未启动'}`;
  }
}

function updateSyncUI(running, last) {
  syncOn = running;
  const abortBtn = document.getElementById('btn-abort');
  const syncBtn = document.getElementById('btn-sync');
  const progressCard = document.getElementById('card-sync-progress');
  
  if (abortBtn) abortBtn.style.display = running ? '' : 'none';
  if (syncBtn) {
    syncBtn.textContent = running ? '进行中…' : '立即执行';
    syncBtn.disabled = running;
  }
  if (progressCard) progressCard.style.display = running ? '' : 'none';

  const hdr = document.getElementById('hdr-sync');
  if (hdr) {
    hdr.innerHTML = `<span class="dot ${running ? 'dot-busy' : 'dot-off'}"></span>${running ? '同步进行中' : '同步空闲'}`;
  }

  if (last) {
    const s = last.status;
    const ts = last.finished_at ? last.finished_at.substring(0, 16).replace('T', ' ') : '—';
    const lastSyncSpan = document.getElementById('sync-last');
    if (lastSyncSpan) {
      lastSyncSpan.textContent = `上次：${ts} · ${last.total || 0} 个文件 · ${s === 'done' ? '完成' : s}`;
    }

    if (running) {
      const total = last.total || 1;
      const done = last.done || 0;
      const pct = Math.round(done / total * 100);
      const fillEl = document.getElementById('sync-progress-fill');
      const textEl = document.getElementById('sync-progress-text');
      const badgeEl = document.getElementById('sync-pct-badge');
      if (fillEl) fillEl.style.width = pct + '%';
      if (textEl) textEl.textContent = `${pct}% · ${done}/${total}`;
      if (badgeEl) badgeEl.textContent = `${pct}%`;
      _updateSyncStep(s, done, total);
    }
  }
}

function _updateSyncStep(status, done, total) {
  const steps = ['step-local', 'step-snap', 'step-diff', 'step-upload'];
  const map = {
    'running': ['完成', '完成', '完成', `进行中 ${done}/${total}`],
    'uploading': ['完成', '完成', '完成', `上传中 ${done}/${total}`],
    'done': ['完成', '完成', '完成', '完成'],
  };
  const vals = map[status] || ['等待中', '等待中', '等待中', '等待中'];
  steps.forEach((id, i) => {
    const el = document.getElementById(id);
    if (el) {
      el.textContent = vals[i];
      el.className = vals[i].startsWith('完成') ? 'step-ok' :
                     vals[i].startsWith('进行') || vals[i].startsWith('上传') ? 'step-running' : 'step-wait';
    }
  });
}

function updateMetrics(stats, queue, snapAge) {
  if (!stats) return;
  
  const todayEl = document.getElementById('m-today');
  const todaySubEl = document.getElementById('m-today-sub');
  const queueEl = document.getElementById('m-queue');
  const queueSubEl = document.getElementById('m-queue-sub');
  const totalEl = document.getElementById('m-total');
  const totalSubEl = document.getElementById('m-total-sub');
  const snapEl = document.getElementById('m-snap');
  const snapSubEl = document.getElementById('m-snap-sub');
  
  if (todayEl) todayEl.textContent = stats.today_total || 0;
  if (todaySubEl) todaySubEl.textContent = `成功 ${stats.today_success || 0} · 失败 ${stats.today_failed || 0}`;
  
  const waiting = (queue && queue.waiting) ? queue.waiting.length : 0;
  const active = (queue && queue.uploading) ? queue.uploading.length : 0;
  if (queueEl) queueEl.textContent = waiting;
  if (queueSubEl) queueSubEl.textContent = `${active} 个上传中`;
  
  if (totalEl) totalEl.textContent = stats.all_time_total || 0;
  if (totalSubEl) totalSubEl.textContent = fmtBytes(stats.all_time_bytes || 0);
  
  if (snapAge !== null && snapAge !== undefined) {
    if (snapEl) snapEl.textContent = '已缓存';
    if (snapSubEl) snapSubEl.textContent = `${snapAge.toFixed(1)}h 前更新`;
  }
}

function updateQueue(queue) {
  if (!queue) return;
  const uploading = queue.uploading || [];
  const waiting = queue.waiting || [];

  const ul = document.getElementById('uploading-list');
  const uploadingBadge = document.getElementById('badge-uploading');
  
  if (ul) {
    if (uploading.length === 0) {
      ul.innerHTML = '<div class="empty">当前无上传任务</div>';
      if (uploadingBadge) uploadingBadge.style.display = 'none';
    } else {
      if (uploadingBadge) {
        uploadingBadge.style.display = '';
        uploadingBadge.textContent = uploading.length + ' 个';
      }
      ul.innerHTML = uploading.map(t => `
        <div class="upload-item">
          <div class="row-between">
            <div class="upload-name">${escapeHtml(t.name)}</div>
            <div style="font-size:11px;color:#aaa;flex-shrink:0;margin-left:8px">${t.progress}% · ${fmtBytes(t.transferred)} / ${fmtBytes(t.file_size)}</div>
          </div>
          <div class="progress-wrap"><div class="progress-bar"><div class="progress-fill" style="width:${t.progress}%"></div></div></div>
          <div class="upload-meta">来自：${t.source === 'monitor' ? '实时监控' : '全量同步'}</div>
        </div>`).join('');
    }
  }

  const wl = document.getElementById('waiting-list');
  const queueBadge = document.getElementById('badge-queue');
  
  if (queueBadge) queueBadge.textContent = waiting.length;
  if (wl) {
    if (waiting.length === 0) {
      wl.innerHTML = '<div class="empty">队列为空</div>';
    } else {
      wl.innerHTML = waiting.slice(0, 10).map(t => `
        <div class="queue-item">
          <div class="queue-name">${escapeHtml(t.name)}</div>
          <div class="queue-meta">${fmtBytes(t.file_size)} · ${t.source === 'monitor' ? '实时监控' : '全量同步'}${t.retry_count > 0 ? ' · 重试 ' + t.retry_count : ''}</div>
        </div>`).join('');
    }
  }
}

// ── 日志处理 ──────────────────────────────────────────────
function appendLog(entry) {
  if (!matchFilter(entry)) return;
  const wrap = document.getElementById('log-container');
  if (!wrap) return;
  
  const div = document.createElement('div');
  div.className = 'log-line';
  const lvClass = entry.level === 'ERROR' ? 'lv-err' : entry.level === 'WARNING' ? 'lv-warn' :
    entry.message && (entry.message.includes('Done') || entry.message.includes('成功')) ? 'lv-ok' : 'lv-info';
  div.innerHTML = `<span class="log-time">${escapeHtml(entry.time)}</span><span class="log-lv ${lvClass}">${escapeHtml(entry.level)}</span><span class="log-msg">${escapeHtml(entry.message)}</span>`;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
  while (wrap.children.length > 300) wrap.removeChild(wrap.firstChild);
}

function matchFilter(entry) {
  if (logFilter === 'error') return ['ERROR', 'WARNING'].includes(entry.level);
  if (logFilter === 'success') return entry.message && entry.message.toLowerCase().includes('done') || (entry.message && entry.message.includes('成功'));
  return true;
}

function filterLogs(f) {
  logFilter = f;
  ['all', 'err', 'ok'].forEach(k => {
    const btn = document.getElementById('lf-' + k);
    if (btn) btn.classList.remove('active');
  });
  const activeBtn = document.getElementById('lf-' + (f === 'all' ? 'all' : f === 'error' ? 'err' : 'ok'));
  if (activeBtn) activeBtn.classList.add('active');
  
  const wrap = document.getElementById('log-container');
  if (wrap) {
    wrap.innerHTML = '';
    allLogs.filter(matchFilter).forEach(appendLog);
  }
}

function clearLogs() {
  allLogs = [];
  const wrap = document.getElementById('log-container');
  if (wrap) wrap.innerHTML = '';
}

// ── 监控控制 ──────────────────────────────────────────────
function toggleMonitor() {
  const url = monitorOn ? '/api/monitor/stop' : '/api/monitor/start';
  fetch(url, { method: 'POST' }).then(() => pollStatus());
}

function toggleScheduler() {
  schedOn = !schedOn;
  const togTrack = document.getElementById('tog-sched');
  const togKnob = document.getElementById('knob-sched');
  if (togTrack) togTrack.classList.toggle('on', schedOn);
  if (togKnob) togKnob.classList.toggle('on', schedOn);
  
  const badge = document.getElementById('badge-sched');
  if (badge) {
    badge.textContent = schedOn ? '已启用' : '未启用';
    badge.className = 'badge ' + (schedOn ? 'badge-ok' : 'badge-muted');
  }
  
  fetch('/api/config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ scheduler_enabled: schedOn })
  }).then(r => r.json()).then(d => {
    if (!d.ok) {
      showToast('保存调度器状态失败', true);
      schedOn = !schedOn;
      if (togTrack) togTrack.classList.toggle('on', schedOn);
      if (togKnob) togKnob.classList.toggle('on', schedOn);
    }
  });
}

// ── 同步控制 ──────────────────────────────────────────────
function startSync() {
  fetch('/api/sync/start', { method: 'POST' }).then(r => r.json()).then(d => {
    if (!d.ok) alert(d.error || '无法启动同步');
    else pollStatus();
  });
}

function abortSync() {
  if (!confirm('确认中止当前同步任务？')) return;
  fetch('/api/sync/abort', { method: 'POST' }).then(() => pollStatus());
}

// ── 队列控制 ──────────────────────────────────────────────
function clearQueue() {
  if (!confirm('确认清空等待队列？')) return;
  fetch('/api/queue/clear', { method: 'POST' }).then(() => pollStatus());
}

// ── 配置加载和保存 ────────────────────────────────────────
function loadConfig() {
  fetch('/api/config').then(r => r.json()).then(data => {
    cfg = data;
    
    const fields = {
      'cfg-webdav-url': data.webdav_url || '',
      'cfg-remote-dir': data.webdav_remote_dir || '/',
      'cfg-username': data.webdav_username || '',
      'cfg-watch-dir': data.local_watch_dir || '/data',
      'cfg-concurrent': data.concurrent_uploads || 3,
      'cfg-retry': data.retry_count || 3,
      'cfg-timeout': data.single_file_timeout_minutes || 60,
      'cfg-sched-time': data.scheduler_time || '03:00',
      'cfg-speed': data.sync_speed_limit || '10M',
      'cfg-ttl': data.webdav_snapshot_ttl_hours || 23,
      'cfg-logdays': data.log_retain_days || 30,
    };
    
    for (const [id, val] of Object.entries(fields)) {
      const el = document.getElementById(id);
      if (el) el.value = val;
    }
    
    document.getElementById('cfg-password').value = '';
    
    const ow = data.overwrite_policy || 'skip_if_same_size';
    document.querySelectorAll('input[name="ow"]').forEach(r => {
      r.checked = r.value === ow;
    });
    
    schedOn = !!data.scheduler_enabled;
    const togTrack = document.getElementById('tog-sched');
    const togKnob = document.getElementById('knob-sched');
    if (togTrack) togTrack.classList.toggle('on', schedOn);
    if (togKnob) togKnob.classList.toggle('on', schedOn);
    
    const schedBadge = document.getElementById('badge-sched');
    if (schedBadge) {
      schedBadge.textContent = schedOn ? '已启用' : '未启用';
      schedBadge.className = 'badge ' + (schedOn ? 'badge-ok' : 'badge-muted');
    }
    
    renderTags('tags-ext', data.video_extensions || [], 'ext');
    renderTags('tags-ignore', data.ignore_dirs || [], 'ignore');
    
    window.currentConfig = data;
  }).catch(err => {
    console.error('Failed to load config:', err);
    showToast('加载配置失败', true);
  });
}

function saveSection(section) {
  let payload = {};
  
  if (section === 'webdav') {
    const newPassword = document.getElementById('cfg-password').value;
    payload = {
      webdav_url: document.getElementById('cfg-webdav-url').value.trim(),
      webdav_remote_dir: document.getElementById('cfg-remote-dir').value.trim(),
      webdav_username: document.getElementById('cfg-username').value.trim(),
    };
    if (newPassword && !newPassword.startsWith('•')) {
      payload.webdav_password = newPassword;
    }
  } else if (section === 'dirs') {
    payload = {
      local_watch_dir: document.getElementById('cfg-watch-dir').value.trim(),
      video_extensions: getTagValues('tags-ext'),
      ignore_dirs: getTagValues('tags-ignore'),
    };
  }
