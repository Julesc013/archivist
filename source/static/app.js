'use strict';
const $ = id => document.getElementById(id), token = document.querySelector('meta[name=ap20-token]').content;
const PAGE_SIZE = 100;
const S = { status: null, doctor: null, scans: [], plans: [], builds: [], replicas: [], destinations: [], view: 'sources', scan: null, scanRecord: null, node: null, parent: null, treeOffset: 0, plan: null, planRecord: null, packages: [], package: null, packageRecord: null, packagePlan: null, packageOffset: 0, memberOffset: 0, selected: new Set(), members: new Set(), tasks: [], active: null, appearance: 'system', offsets: {}, more: {}, recoveryPackages: null, recoverySearch: null, recoveryOffset: 0 };
const listButtons = { scans: 'scan-load-more', plans: 'plan-load-more', builds: 'build-load-more', replicas: 'replica-load-more' };
const waitingTasks = new Map();
let pollingTimer = null, pollingBusy = false, serviceStopped = false;
function el(tag, text, cls) { const e = document.createElement(tag); if (text !== undefined)
    e.textContent = String(text); if (cls)
    e.className = cls; return e; }
function clear(e) { e.replaceChildren(); return e; }
function size(n) { n = Number(n) || 0; function fmt(b, u) { let x = n, i = 0; while (x >= b && i < u.length - 1) {
    x /= b;
    i++;
} return `${x.toLocaleString(undefined, { maximumFractionDigits: 2 })} ${u[i]}`; } return `${fmt(1000, ['B', 'KB', 'MB', 'GB', 'TB', 'PB'])} / ${fmt(1024, ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'])}`; }
function duration(n) { if (n === null || n === undefined)
    return '—'; if (n < 60)
    return `${Math.round(n)}s`; if (n < 3600)
    return `${Math.floor(n / 60)}m ${Math.round(n % 60)}s`; return `${Math.floor(n / 3600)}h ${Math.floor(n % 3600 / 60)}m`; }
function notice(text, error = false) { $('notice').hidden = false; $('notice').className = error ? 'error' : ''; $('notice').textContent = text; }
async function request(url, body) { const opts = { headers: { 'X-AP20-Token': token } }; if (body !== undefined) {
    opts.method = 'POST';
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
} const response = await fetch(url, opts); const value = await response.json(); if (!response.ok || value.error)
    throw new Error(value.error ? `${value.error.code}: ${value.error.message}` : `HTTP ${response.status}`); return value; }
const read = (action, args = {}) => request(`/api/read?action=${encodeURIComponent(action)}&args=${encodeURIComponent(JSON.stringify(args))}`);
const safe = fn => (...args) => Promise.resolve().then(() => fn(...args)).catch(e => notice(e.message, true));
function button(text, fn, cls) { const b = el('button', text, cls); b.type = 'button'; b.addEventListener('click', safe(fn)); return b; }
function badge(value) { return el('span', value, 'badge ' + (value === 'BLOCKED' || value === 'FAILED' ? 'blocked' : value === 'REVIEW' || value === 'SMALL' || value === 'INTERRUPTED' ? 'review' : 'ready')); }
function planLabel(p) {
    const created = (p.created || '').replace('T', ' ').replace('Z', ' UTC');
    return `${p.label} · ${p.counts.packages} packages · ${p.state} · ${created} · ${p.id}`;
}
function reasonText(reason) {
    return ({ DIRECT_FILES_TOGETHER: 'Direct files kept together.', LOOSE_FILES_SPLIT_LOCALLY: 'Loose files split within their parent directory to meet the package target.', WHOLE_DIRECTORY: 'A complete directory fits within the package limit.', WHOLE_SIBLINGS_COMBINED: 'Small sibling directories kept whole and grouped together.', DIRECTORY_METADATA: 'Directory structure and metadata recorded separately.', MANUAL_CODEC: 'Encoding changed in a saved revision.', MANUAL_MERGE: 'Packages merged by the operator.', MANUAL_MOVE: 'Membership changed by the operator.' })[reason] || String(reason || '').replaceAll('_', ' ').toLowerCase();
}
function planActions() {
    $('merge-packages').disabled = !S.plan || S.selected.size < 2;
    $('open-build').disabled = $('build-plan').disabled = !S.plan;
    const selected = S.packageRecord && S.packagePlan === S.plan && S.packageRecord.id === S.package;
    $('edit-codec').disabled = !selected || S.packageRecord.kind !== 'data';
    $('sample-codec').disabled = !selected || S.packageRecord.kind !== 'data';
    $('move-members').disabled = !selected || !S.members.size;
}
function clearPackage() {
    S.package = S.packageRecord = S.packagePlan = null;
    S.members.clear(); S.memberOffset = 0;
    $('package-name').textContent = 'Select a package';
    $('package-reason').textContent = 'Inspect its original paths before changing encoding or membership.';
    for (const id of ['member-rows', 'member-pages', 'sample-results']) clear($(id));
    planActions();
}
function selectPlan(id) {
    S.plan = id || null; S.planRecord = null; S.packages = [];
    S.selected.clear(); S.packageOffset = 0; clearPackage();
    for (const target of ['package-rows', 'package-pages', 'plan-summary', 'plan-revision-note', 'allocation-results']) clear($(target));
    planActions();
}
async function packageDetail() {
    if (!S.plan || !S.package) throw new Error('Select a package.');
    const plan = S.plan, id = S.package;
    if (S.packagePlan === plan && S.packageRecord?.id === id) return S.packageRecord;
    const value = await read('package', { plan_id: plan, package_id: id });
    if (S.plan !== plan || S.package !== id) throw new Error('Package selection changed; try the action again.');
    S.packageRecord = value; S.packagePlan = plan; planActions();
    return value;
}
async function loadList(kind, append = false) {
    const offset = append ? (S.offsets[kind] || 0) : 0;
    const rows = await read(kind, { limit: PAGE_SIZE, offset });
    S[kind] = append ? [...new Map([...S[kind], ...rows].map(r => [r.id, r])).values()] : rows;
    S.offsets[kind] = offset + rows.length; S.more[kind] = rows.length === PAGE_SIZE;
    $(listButtons[kind]).hidden = !S.more[kind];
    return rows;
}
function field(title, value = '', type = 'text', hint = '') { const label = el('label', title); const input = el('input'); input.type = type; input.setAttribute('aria-label', title); if (type === 'number') input.step = 'any'; input.value = value; if (hint)
    input.title = hint; label.append(input); return { label, input }; }
function select(title, options, value) { const label = el('label', title), input = el('select'); input.setAttribute('aria-label', title); for (const [key, name] of options) {
    const o = el('option', name);
    o.value = key;
    input.append(o);
} input.value = value; label.append(input); return { label, input }; }
function checkbox(title, value = false) { const label = el('label', undefined, 'check'), input = el('input'); input.type = 'checkbox'; input.checked = value; label.append(input, document.createTextNode(title)); return { label, input }; }
let onSubmit = null;
function dialog(title, body, submit = 'Continue', handler = null) { $('dialog-title').textContent = title; $('dialog-body').replaceChildren(...(Array.isArray(body) ? body : [body])); $('dialog-error').textContent = ''; $('dialog-submit').textContent = submit; $('dialog-submit').hidden = !handler; onSubmit = handler; $('dialog').showModal(); }
function closeDialog() { $('dialog').close(); onSubmit = null; }
$('dialog-close').onclick = closeDialog;
$('dialog-cancel').onclick = closeDialog;
$('dialog-form').addEventListener('submit', async (e) => { e.preventDefault(); if (!onSubmit)
    return; try {
    await onSubmit();
}
catch (error) {
    if ($('dialog').open) $('dialog-error').textContent = error.message; else notice(error.message, true);
} });
function pager(container, total, offset, step, fn) { clear(container); container.append(el('span', total ? `${offset + 1}–${Math.min(total, offset + step)} of ${total.toLocaleString()}` : '0 records')); const prev = button('Previous', () => fn(Math.max(0, offset - step))), next = button('Next', () => fn(offset + step)); prev.disabled = offset === 0; next.disabled = offset + step >= total; container.append(prev, next); }
let preferenceTimer;
function prefs() { clearTimeout(preferenceTimer); preferenceTimer = setTimeout(() => { if (S.active)
    return; request('/api/preferences', { view: S.view, appearance: S.appearance, selected_plan: S.plan, selected_snapshot: S.scan }).catch(() => { }); }, 350); }
function appearance(value) { S.appearance = value; if (value === 'system')
    document.documentElement.removeAttribute('data-appearance');
else
    document.documentElement.dataset.appearance = value; $('appearance').value = value; prefs(); }
function view(name) { S.view = name; document.querySelectorAll('.view').forEach(x => x.hidden = x.id !== `view-${name}`); document.querySelectorAll('[data-view]').forEach(b => b.setAttribute('aria-current', b.dataset.view === name ? 'page' : 'false')); prefs(); }
document.querySelectorAll('[data-view]').forEach(b => b.onclick = safe(async () => { view(b.dataset.view); if (S.view === 'archive')
    await archiveView(); }));
$('appearance').onchange = () => appearance($('appearance').value);
async function refresh() {
    const [status, , , dest] = await Promise.all([read('status'), loadList('scans'), loadList('plans'), read('destinations')]);
    S.status = status; S.destinations = dest;
    $('app-version').textContent = status.version;
    $('workspace-name').textContent = status.workspace; $('workspace-name').title = status.workspace;
    renderScans(); renderPlanSelector();
    if (S.scan) await tree();
    if (S.plan) await packages();
    if (S.view === 'archive') await archiveView();
    planActions();
}
$('refresh').onclick = safe(refresh);
async function work(action, args, completed) {
    const response = await request('/api/task', { action, args });
    notice(`Queued: ${action.replaceAll('_', ' ')}`);
    const finished = new Promise((resolve, reject) => waitingTasks.set(response.task_id, { resolve, reject }));
    schedulePolling(0);
    const t = await finished;
    await refresh();
    notice(`${action.replaceAll('_', ' ')}: complete`);
    if (completed) await completed(t.result);
    return t.result;
}
async function reviewAndRun(action, args) { closeDialog(); const r = await work('preflight_' + action, args); const pre = el('details'), summary = el('summary', 'Exact review record'), facts = el('dl', undefined, 'review-facts'); pre.append(summary, el('pre', JSON.stringify(r, null, 2))); for (const [title, value] of [['Action', action], ['Source', r.archive_set || r.plan_id], ['Destination', r.output || r.target], ['Packages', r.packages?.join(', ')], ['Bytes', r.logical_bytes || r.actual_payload_bytes || r.estimated_required_bytes], ['Excluded observations', r.excluded_observations]]) { if (value !== undefined) facts.append(el('dt', title), el('dd', title === 'Bytes' ? size(value) : value)); } dialog(`Review ${action}`, [el('p', action === 'restore' ? 'Writes only to the new destination shown below. Existing files are never overwritten.' : 'Confirm the source, selection and destination. Original files are retained.'), facts, pre], `Confirm ${action}`, async () => { closeDialog(); await work(action, { ...args, approval: r.approval }, result => { notice(`${action}: ${result.state || 'complete'}`); if (action === 'restore')
    showRecovery(result); }); }); }
function renderScans() { const box = clear($('scan-list')); if (!S.scans.length) {
    box.append(el('p', 'No recorded sources. Scan one directory to begin.', 'empty'));
    return;
} const visible = S.scanRecord && S.scan === S.scanRecord.id && !S.scans.some(x => x.id === S.scan) ? [S.scanRecord, ...S.scans] : S.scans; for (const scan of visible) {
    const b = button('', async () => { S.scan = scan.id; S.node = null; S.treeOffset = 0; await tree(); prefs(); renderScans(); }, scan.id === S.scan ? 'selected' : '');
    b.append(el('strong', scan.label || scan.id), el('small', `${scan.backend} · ${scan.state} · ${scan.counts.files || 0} files`), el('small', size(scan.counts.eligible_bytes || 0)));
    b.title = scan.root;
    box.append(b);
} }
async function tree() { if (!S.scan)
    return; const scanId = S.scan; const r = await read('browse', { snapshot_id: scanId, node_id: S.node, offset: S.treeOffset }); if (S.scan !== scanId) return; S.scanRecord = { ...(S.scans.find(x => x.id === scanId) || S.scanRecord || {}), ...r.scan }; S.node = r.directory.id; S.parent = r.directory.parent; $('tree-path').textContent = r.directory.path || '/'; $('tree-up').disabled = S.parent === null; const summary = clear($('scan-summary')); for (const text of [`${r.scan.backend} acquisition`, `${r.scan.counts.eligible_files} included files`, `${r.scan.counts.excluded} excluded`, `${r.scan.counts.errors} errors`])
    summary.append(el('span', text)); const rows = clear($('tree-rows')); for (const n of r.rows) {
    const tr = el('tr'), name = el('td');
    if (n.kind === 'directory')
        name.append(button(n.name || '/', async () => { S.node = n.id; S.treeOffset = 0; await tree(); }, 'link'));
    else
        name.textContent = n.name;
    tr.append(name, el('td', n.kind), el('td', size(n.kind === 'directory' ? n.total_bytes : n.size)), el('td', n.eligible ? 'Yes' : 'Excluded'));
    rows.append(tr);
} pager($('tree-pages'), r.total, S.treeOffset, 100, async (n) => { S.treeOffset = n; await tree(); }); await typesAndIssues(); }
$('tree-up').onclick = safe(async () => { S.node = S.parent; S.treeOffset = 0; await tree(); });
async function typesAndIssues() { if (!S.scan)
    return; const [types, issues] = await Promise.all([read('types', { snapshot_id: S.scan, limit: 1000 }), read('issues', { snapshot_id: S.scan, limit: 100 })]); const list = clear($('type-list')); list.append(el('h2', `${types.total} observed suffixes`)); if (types.total > types.rows.length) list.append(el('p', `Showing ${types.rows.length} of ${types.total}; use CLI pagination or the full scan export for the remainder.`, 'muted')); for (const t of types.rows) {
    list.append(el('p', `${t.extension ? '.' + t.extension : '(no extension)'} · ${t.files.toLocaleString()} files · ${size(t.bytes)} · ${t.class}`));
} const errors = clear($('issue-list')); errors.append(el('h2', 'Recorded issues')); const count = S.scans.find(s => s.id === S.scan)?.counts.issues || 0; if (count > issues.length) errors.append(el('p', `Showing ${issues.length} of ${count}; CLI and full scan export retain every issue.`, 'muted')); if (!issues.length)
    errors.append(el('p', 'No acquisition issues recorded. This does not establish full filesystem-metadata fidelity.')); for (const i of issues) {
    const p = el('p', `${i.code} · ${i.path} · ${i.detail}`, i.severity === 'error' ? 'error' : '');
    errors.append(p);
} }
function newScan() { const root = field('Source directory', '', 'text', 'Absolute local or mounted path. Source content is never modified.'), label = field('Label (optional)'), backend = select('Acquisition', [['everything', 'Everything · required, no fallback'], ['filesystem', 'Filesystem · enumerate directly'], ['auto', 'Auto · report any fallback']], S.doctor?.platform.startsWith('Windows') ? 'everything' : 'filesystem'), es = field('es.exe path (Windows Everything only)'), instance = field('Everything instance', '1.5a'), hash = checkbox('Read every file now and record SHA-256 (slower)', false); backend.input.addEventListener('change', () => { hash.input.disabled = backend.input.value !== 'filesystem'; if (hash.input.disabled) hash.input.checked = false; }); backend.input.dispatchEvent(new Event('change')); dialog('Scan source', [root.label, label.label, backend.label, es.label, instance.label, hash.label, el('p', 'The index is an observation, not a frozen snapshot. Everything requires a running instance and the separate ES client.', 'muted')], 'Scan', async () => { if (!root.input.value.trim())
    throw new Error('Enter a source directory.'); const args = { root: root.input.value, label: label.input.value || null, backend: backend.input.value, es: es.input.value || null, instance: instance.input.value, hash_files: hash.input.checked }; closeDialog(); await work('scan', args, async (r) => { S.scan = r.snapshot_id; S.node = null; view('sources'); renderScans(); await tree(); notice(`Scan complete · actual backend: ${r.backend} · ${r.counts.errors} errors · ${r.counts.excluded} excluded`); }); }); }
$('new-scan').onclick = newScan;
function newPlan() { const eligible = S.scans.filter(s => ['COMPLETE', 'REVIEW'].includes(s.state)); const chosen = el('div', undefined, 'object-checks'), checks = []; for (const s of eligible) {
    const c = checkbox(`${s.label} · ${size(s.counts.eligible_bytes)} · ${s.id}`, s.id === S.scan);
    checks.push([s, c]);
    chosen.append(c.label);
} const label = field('Plan name', 'Archive plan'), min = field('Minimum goal · GB', '10', 'number'), target = field('Target · GB', '100', 'number'), max = field('Maximum · GB', '200', 'number'), codec = select('Encoding', [['auto', 'Automatic · Zstandard for text-dominant groups'], ['none', 'Plain PAX TAR'], ['zstd', 'Zstandard for all data packages'], ['gzip', 'gzip for all data packages']], 'auto'), level = field('Compression level', '3', 'number'), row = el('div', undefined, 'row'); row.append(min.label, target.label, max.label); dialog('Create directory-first plan', [chosen, label.label, row, codec.label, level.label, el('p', 'Fitting subtrees stay intact. Larger directories are examined deeper; loose files split only inside their parent. Small remainders are allowed. No assumed compression savings are used to force a package to fit.', 'muted')], 'Create plan', async () => { const snapshots = checks.filter(x => x[1].input.checked).map(x => x[0].id); if (!snapshots.length)
    throw new Error('Select at least one completed scan.'); const args = { snapshots, label: label.input.value, policy: { minimum: Math.round(Number(min.input.value) * 1e9), target: Math.round(Number(target.input.value) * 1e9), maximum: Math.round(Number(max.input.value) * 1e9), codec: codec.input.value, level: Number(level.input.value) } }; closeDialog(); await work('plan', args, async (r) => { S.plan = r.id; S.package = null; S.packageOffset = 0; S.selected.clear(); view('plan'); renderPlanSelector(); await packages(); }); }); }
$('new-plan').onclick = newPlan;
$('use-plan').onclick = newPlan;
function renderPlanSelector() {
    const sel = clear($('plan-select')); sel.append(new Option('Select a saved plan', ''));
    const visible = S.planRecord && S.planRecord.id === S.plan && !S.plans.some(p => p.id === S.plan) ? [S.planRecord, ...S.plans] : S.plans;
    for (const p of visible) sel.append(new Option(planLabel(p), p.id));
    sel.value = S.plan || '';
}
$('plan-select').onchange = safe(async () => { selectPlan($('plan-select').value); await packages(); prefs(); });
$('scan-load-more').onclick = safe(async () => { await loadList('scans', true); renderScans(); });
$('plan-load-more').onclick = safe(async () => { await loadList('plans', true); renderPlanSelector(); });
async function packages() { if (!S.plan)
    return; const planId = S.plan, offset = S.packageOffset; const r = await read('packages', { plan_id: planId, offset }); if (S.plan !== planId || S.packageOffset !== offset) return; S.packages = r.packages; S.planRecord = r.plan; renderPlanSelector(); const revision = clear($('plan-revision-note')); revision.append(el('span', `Saved ${r.plan.created}. ${r.plan.parent_plan ? 'Revision of ' + r.plan.parent_plan + '.' : 'Original plan.'} Membership was checked when this revision was saved.`)); if (r.plan.parent_plan) revision.append(button('Open previous revision', async () => { selectPlan(r.plan.parent_plan); await packages(); prefs(); }, 'link')); const summary = clear($('plan-summary')); for (const text of [r.plan.state, `${r.plan.counts.files.toLocaleString()} files`, size(r.plan.counts.logical_bytes), `${r.total} packages`, `${r.plan.counts.excluded_observations} excluded`])
    summary.append(el('span', text)); const rows = clear($('package-rows')); for (const p of r.packages) {
    const tr = el('tr');
    tr.dataset.select = p.id;
    if (S.package === p.id)
        tr.classList.add('selected');
    const box = el('input');
    box.type = 'checkbox';
    box.setAttribute('aria-label', `Select ${p.id}`);
    box.checked = S.selected.has(p.id);
    box.onclick = e => e.stopPropagation();
    box.onchange = () => { if (box.checked)
        S.selected.add(p.id);
    else
        S.selected.delete(p.id); planActions(); };
    const selectCell = el('td');
    selectCell.append(box);
    const name = el('td', p.id);
    name.append(el('small', p.anchor || (p.kind === 'directories' ? 'Directory metadata' : 'Root files')));
    tr.append(selectCell, name, el('td', p.file_count.toLocaleString()), el('td', size(p.logical_bytes)), el('td', p.codec === 'none' ? 'TAR' : `TAR + ${p.codec}`));
    const status = el('td');
    status.append(badge(p.status));
    tr.append(status);
    tr.onclick = safe(async () => { S.package = p.id; S.packageRecord = p; S.packagePlan = S.plan; S.memberOffset = 0; S.members.clear(); clear($('sample-results')); document.querySelectorAll('#package-rows tr').forEach(row => row.classList.toggle('selected', row.dataset.select === p.id)); await members(); });
    tr.tabIndex = 0;
    tr.onkeydown = e => { if (e.target === tr && (e.key === 'Enter' || e.key === ' ')) {
        e.preventDefault();
        tr.click();
    } };
    rows.append(tr);
} pager($('package-pages'), r.total, S.packageOffset, 100, async (n) => { S.packageOffset = n; await packages(); }); if (S.package && (!S.packageRecord || S.packagePlan !== S.plan)) await members();
else if (!S.package) clearPackage(); planActions(); prefs(); }
async function members() { if (!S.package)
    return; const planId = S.plan, packageId = S.package, offset = S.memberOffset; const [r, p] = await Promise.all([read('members', { plan_id: planId, package_id: packageId, offset }), packageDetail()]); if (S.plan !== planId || S.package !== packageId || S.memberOffset !== offset) return; $('package-name').textContent = packageId; $('package-reason').textContent = `${reasonText(p.reason)} Estimated archive budget: ${size(p.estimated_bytes)}. Not a compression forecast.`; const rows = clear($('member-rows')); for (const m of r.rows) {
    const tr = el('tr'), c = el('td'), box = el('input');
    box.type = 'checkbox';
    box.disabled = m.kind !== 'file';
    box.checked = S.members.has(m.id);
    box.setAttribute('aria-label', `Select ${m.path}`);
    box.onchange = () => { if (box.checked)
        S.members.add(m.id);
    else
        S.members.delete(m.id); planActions(); };
    c.append(box);
    tr.append(c, el('td', m.path || '/', 'path'), el('td', size(m.size)));
    rows.append(tr);
} pager($('member-pages'), r.total, S.memberOffset, 100, async (n) => { S.memberOffset = n; await members(); }); planActions(); }
async function edited(result) { selectPlan(result.id); await refresh(); view('plan'); notice('Saved a new plan revision. Previous decisions remain unchanged.'); }
$('edit-codec').onclick = safe(async () => { if (!S.package)
    throw new Error('Select a package.'); const p = await packageDetail(), planId = S.plan, packageId = p.id; if (p.kind !== 'data') throw new Error('Directory metadata stays uncompressed.'); const codec = select('Encoding', [['none', 'Plain PAX TAR'], ['zstd', 'PAX TAR + Zstandard'], ['gzip', 'PAX TAR + gzip']], p.codec), level = field('Level', p.level, 'number'); dialog(`Encoding · ${packageId}`, [codec.label, level.label, el('p', 'This creates a new immutable plan revision. Directory metadata stays uncompressed.', 'muted')], 'Save revision', async () => { const args = { plan_id: planId, codec_changes: { [packageId]: { codec: codec.input.value, level: Number(level.input.value) } } }; closeDialog(); await work('revise', args, edited); }); });
$('merge-packages').onclick = safe(async () => { if (S.selected.size < 2)
    throw new Error('Select at least two payload packages from the same scan with the same encoding.'); const args = { plan_id: S.plan, merge: [...S.selected] }; dialog('Merge complete packages', el('p', `Merge ${[...S.selected].join(', ')} into a new revision. Original paths stay unchanged; an oversized result will be visibly blocked.`), 'Merge', async () => { closeDialog(); await work('revise', args, edited); }); });
$('move-members').onclick = safe(async () => {
    if (!S.members.size) throw new Error('Select one or more file members.');
    const source = await packageDetail(), planId = S.plan, nodeIds = [...S.members];
    const search = field('Find target package by ID or directory');
    const target = select('Target', [['', 'New plain-TAR package']], '');
    const pages = el('div', undefined, 'pager'), hint = el('p', 'Searching all compatible packages…', 'muted');
    const remembered = new Map(); let requestNumber = 0;
    async function loadTargets(offset = 0) {
        const current = ++requestNumber;
        const r = await read('packages', { plan_id: planId, kind: 'data', snapshot_id: source.snapshot_id, exclude_package_id: source.id, query: search.input.value.trim(), offset, limit: PAGE_SIZE });
        if (current !== requestNumber) return;
        const chosen = target.input.value;
        for (const p of r.packages) remembered.set(p.id, `${p.id} · ${p.anchor || 'Root files'} · ${p.codec === 'none' ? 'TAR' : p.codec}`);
        clear(target.input); target.input.append(new Option('New plain-TAR package', ''));
        if (chosen && !r.packages.some(p => p.id === chosen)) target.input.append(new Option(remembered.get(chosen), chosen));
        for (const p of r.packages) target.input.append(new Option(remembered.get(p.id), p.id));
        target.input.value = chosen;
        hint.textContent = `${r.total.toLocaleString()} compatible existing packages match. Search includes packages outside the visible plan page.`;
        pager(pages, r.total, offset, PAGE_SIZE, loadTargets);
    }
    search.input.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); safe(() => loadTargets())(); } });
    dialog('Move selected files', [search.label, button('Search targets', () => loadTargets()), target.label, hint, pages, el('p', 'Manual movement can reduce restore locality. Coverage is checked again; the old plan is not edited.', 'muted')], 'Save revision', async () => {
        const args = { plan_id: planId, move: { node_ids: nodeIds, target: target.input.value || null } };
        closeDialog(); await work('revise', args, edited);
    });
    await loadTargets();
});
$('sample-codec').onclick = safe(async () => { if (!S.package)
    throw new Error('Select a payload package.'); dialog('Read compression samples', el('p', 'Reads up to 32 MiB from start, middle and end windows of the largest files. This is a biased sample, not a guaranteed ratio for the archive. No settings will change.'), 'Read and test', async () => { closeDialog(); await work('sample', { plan_id: S.plan, package_id: S.package }, r => { const out = clear($('sample-results')); out.append(el('h2', 'Measured sample only')); for (const v of r.results)
    out.append(el('p', `${v.codec} ${v.level} · ${(100 * v.encoded_input_ratio).toFixed(1)}% of input · ${duration(v.encode_seconds)} encode / ${duration(v.decode_seconds)} decode`)); out.append(el('p', r.basis, 'muted')); }); }); });
$('media-preset').onchange = () => { $('media-capacity').value = $('media-preset').value; };
$('fit-media').onclick = safe(async () => { if (!S.plan)
    throw new Error('Select a plan.'); const n = Number($('media-count').value), capacity = Math.round(Number($('media-capacity').value) * 1e9), reserve = Math.round(capacity * Number($('media-reserve').value) / 100); if (!Number.isInteger(n) || n < 1 || n > 50 || !Number.isSafeInteger(capacity) || capacity <= 0 || !Number.isSafeInteger(reserve) || reserve < 0 || reserve >= capacity)
    throw new Error('Choose 1 to 50 media, a positive capacity, and a reserve below that capacity.'); const r = await read('allocate', { plan_id: S.plan, media: Array.from({ length: n }, (_, i) => ({ id: `Medium ${i + 1}`, capacity, reserve, occupied: 0, max_file: capacity })) }); const out = clear($('allocation-results')); for (const m of r.media) {
    const panel = el('div', undefined, 'fit'), title = el('div', undefined, 'fit-title');
    title.append(el('strong', m.id), el('span', `${size(m.used)} used · ${m.packages.length} packages`));
    const bar = el('div', undefined, 'fit-bar');
    const fill = el('span');
    fill.style.width = `${100 * m.used / m.capacity}%`;
    fill.title = m.packages.join(', ');
    const reserved = el('span', undefined, 'reserve');
    reserved.style.width = `${100 * m.reserve / m.capacity}%`;
    reserved.title = 'Configured reserve';
    bar.append(fill, reserved);
    panel.append(title, bar);
    if (m.missing_metadata_package_ids?.length) panel.append(el('p', `Directory metadata also needed: ${m.missing_metadata_package_ids.join(', ')}. These additional copies are not included in this bin's footprint.`, 'error'));
    out.append(panel);
} out.append(el('p', r.unallocated.length ? `Unallocated: ${r.unallocated.join(', ')}` : 'All package objects fit this capacity model. Copy preflight still checks the destination.', r.unallocated.length ? 'error' : 'good')); if (r.metadata_dependencies_complete === false) out.append(el('p', 'Some media still need directory metadata copies for complete metadata-preserving recovery. Review the missing package IDs above.', 'error')); out.append(el('p', `Size basis: ${r.measurement?.basis || 'estimated'}. ${r.basis}`, 'muted')); });
function buildDialog() { if (!S.plan) {
    notice('Choose or create a saved plan first.', true);
    view('plan');
    return;
} const output = field('Staging output directory', '', 'text', 'New directory on your staging drive; separate from source roots. Reuse this exact directory to resume this plan.'), accept = checkbox('I reviewed and accept this scan’s recorded exclusions', false); dialog('Build archive set', [el('p', `Plan: ${S.plan}`), output.label, accept.label, el('p', 'Completed archives are decoded and checked before being committed. Original files and staging artifacts are retained.', 'muted')], 'Review build', () => reviewAndRun('build', { plan_id: S.plan, output: output.input.value, accept_exclusions: accept.input.checked })); }
$('open-build').onclick = buildDialog;
$('build-plan').onclick = buildDialog;
function renderBuilds() { const rows = clear($('build-rows')); for (const b of S.builds) {
    const tr = el('tr'), state = el('td');
    state.append(badge(b.state));
    const actions = el('td');
    actions.append(button('Copy…', () => copyDialog(b.path)), button('Verify', () => work('verify', { bundle: b.path }, showRecovery)), button('Recover', () => { view('restore'); setRecoverySource(b.path); }));
    tr.append(state, el('td', b.plan_id), el('td', b.path, 'path'), actions);
    rows.append(tr);
} if (!S.builds.length) {
    const tr = el('tr'), td = el('td', 'No archive sets built yet.', 'empty');
    td.colSpan = 4;
    tr.append(td);
    rows.append(tr);
} }
function renderReplicas() {
    const rows = clear($('replica-rows'));
    for (const r of S.replicas) {
        const row = el('tr'), state = el('td'), actions = el('td'); state.append(badge(r.state));
        actions.append(button('Verify', () => work('verify', { bundle: r.path }, showRecovery)), button('Recover', () => { view('restore'); setRecoverySource(r.path); }));
        row.append(state, el('td', r.id), el('td', r.path, 'path'), el('td', r.created), actions); rows.append(row);
    }
    if (!S.replicas.length) { const row = el('tr'), cell = el('td', 'No stored copies recorded yet.', 'empty'); cell.colSpan = 5; row.append(cell); rows.append(row); }
}
$('build-load-more').onclick = safe(async () => { await loadList('builds', true); renderBuilds(); });
$('replica-load-more').onclick = safe(async () => { await loadList('replicas', true); renderReplicas(); });
async function archiveView() {
    const [, , history] = await Promise.all([loadList('builds'), loadList('replicas'), read('history', { limit: 20 })]);
    renderBuilds(); renderReplicas();
    const dests = clear($('destination-list')); if (!S.destinations.length)
    dests.append(el('p', 'No destinations registered. Register a disk directory first.', 'empty')); for (const d of S.destinations)
    dests.append(el('p', `${d.label} · ${d.kind} · ${d.enabled ? 'bound' : 'unbound'} · ${d.path}`)); const hist = clear($('history-list')); for (const h of history)
    hist.append(el('p', `${h.created} · ${h.kind} · ${h.state}${h.error ? ' · ' + h.error.message : ''}`, h.state === 'FAILED' ? 'error' : '')); }
function destDialog() { const path = field('Destination directory'), label = field('Label', 'Backup disk'), kind = select('Adapter', [['disk', 'Disk directory'], ['ltfs', 'Mounted LTFS · Linux · experimental']], 'disk'), capacity = field('Capacity budget · GB (optional)', '', 'number'), reserve = field('Additional free-space reserve · GB', '0', 'number'), max = field('Maximum file size · GB (optional)', '', 'number'), ack = checkbox('I understand that the mounted-LTFS adapter is not hardware-qualified'); dialog('Register destination', [path.label, label.label, kind.label, capacity.label, reserve.label, max.label, ack.label, el('p', 'Creates a small identity marker. It never formats, erases or operates a tape drive or robot.', 'muted')], 'Register', async () => { const args = { path: path.input.value, label: label.input.value, kind: kind.input.value, capacity: capacity.input.value ? Math.round(Number(capacity.input.value) * 1e9) : null, max_file: max.input.value ? Math.round(Number(max.input.value) * 1e9) : null, reserve: Math.round(Number(reserve.input.value) * 1e9), experimental: ack.input.checked }; closeDialog(); await work('destination', args); }); }
$('new-destination').onclick = destDialog;
function copyDialog(bundle) { if (!S.destinations.length) {
    destDialog();
    return;
} const dest = select('Destination', S.destinations.map(d => [d.id, `${d.label} · ${d.path}${d.enabled ? '' : ' (unbound)'}`]), S.destinations[0].id), source = field('Archive-set directory', bundle); dialog('Copy verified artifacts', [source.label, dest.label, el('p', 'A fresh readback follows copying. Tape finalization and independent offline verification are separate responsibilities.', 'muted')], 'Review copy', () => reviewAndRun('copy', { bundle: source.input.value, destination: dest.input.value })); }
function showRecovery(r) { const out = clear($('recovery-result')); out.append(el('h2', r.state), el('p', `${r.packages} packages · ${r.members} members · ${size(r.logical_bytes)}`)); if (r.output)
    out.append(el('p', r.output, 'path')); notice(r.state); }
function clearRecoverySelection() {
    S.recoveryPackages = null;
    $('recovery-selection').textContent = 'All packages selected.';
    $('clear-recovery-selection').hidden = true;
}
function resetRecoverySearch() {
    clearRecoverySelection(); S.recoverySearch = null; S.recoveryOffset = 0;
    $('use-recovery-matches').disabled = true;
    for (const id of ['recovery-search-summary', 'recovery-matches', 'recovery-pages', 'recovery-result']) clear($(id));
}
function setRecoverySource(path) { $('recover-source').value = path; resetRecoverySearch(); }
$('recover-source').addEventListener('input', resetRecoverySearch);
$('clear-recovery-selection').onclick = clearRecoverySelection;
function recoveryMetadataText(result) {
    if (result.metadata_completeness === 'complete') return 'Required directory metadata is available.';
    if (result.metadata_completeness === 'missing') return `Directory metadata is incomplete; missing packages: ${(result.missing_metadata_package_ids || []).join(', ') || 'not identified'}. Empty directories or their metadata may be absent.`;
    return 'Original directory metadata completeness is unknown for this archive set. Full directory recovery is not established by this search.';
}
async function findRecovery(offset = 0) {
    const bundle = $('recover-source').value, query = $('recover-query').value.trim();
    if (!bundle) throw new Error('Enter the archive-set directory first.');
    if (!query) throw new Error('Enter a path or filename to find.');
    notice('Searching recorded member manifests…');
    const r = await read('recovery_find', { bundle, query, offset, limit: PAGE_SIZE });
    if ($('recover-source').value !== bundle || $('recover-query').value.trim() !== query) return;
    S.recoverySearch = { bundle, query, ...r }; S.recoveryOffset = offset;
    const rows = clear($('recovery-matches'));
    for (const m of r.rows) { const row = el('tr'); row.append(el('td', m.path, 'path'), el('td', m.package_id), el('td', size(m.size))); rows.append(row); }
    $('recovery-search-summary').textContent = `${r.total.toLocaleString()} matching entries. ${r.package_ids.length} available packages in this lookup. ${recoveryMetadataText(r)} Payload contents have not been verified by this search.`;
    $('use-recovery-matches').disabled = !r.package_ids.length;
    pager($('recovery-pages'), r.total, offset, PAGE_SIZE, findRecovery);
    notice('Manifest search complete. Choose matching packages or keep the full archive set selected.');
}
$('find-recovery').onclick = safe(() => findRecovery());
$('recover-query').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); safe(() => findRecovery())(); } });
$('use-recovery-matches').onclick = safe(() => {
    const result = S.recoverySearch;
    if (!result || result.bundle !== $('recover-source').value || result.query !== $('recover-query').value.trim()) throw new Error('Run the search again before choosing its packages.');
    if (!result.package_ids.length) throw new Error('No matching packages.');
    S.recoveryPackages = { bundle: result.bundle, ids: [...result.package_ids] };
    $('recovery-selection').textContent = `${result.package_ids.length} complete packages selected. ${recoveryMetadataText(result)} Other members in those packages will also be restored.`;
    $('clear-recovery-selection').hidden = false;
});
function recoveryArgs() {
    const bundle = $('recover-source').value;
    if (S.recoveryPackages && S.recoveryPackages.bundle !== bundle) throw new Error('Archive set changed. Choose packages again or select all packages.');
    return { bundle, ...(S.recoveryPackages ? { packages: S.recoveryPackages.ids } : {}) };
}
$('verify-set').onclick = safe(() => work('verify', recoveryArgs(), showRecovery));
$('restore-set').onclick = safe(() => reviewAndRun('restore', { ...recoveryArgs(), output: $('recover-output').value, permissions: $('restore-mode').checked }));
$('source-bind').onclick = safe(async () => { const sources = await read('sources'); if (!sources.length)
    throw new Error('No sources recorded.'); const source = select('Source', sources.map(s => [s.id, `${s.label} · ${s.root}`]), sources[0].id), root = field('Current root directory'); dialog('Bind source location', [source.label, root.label, el('p', 'Binding records the intended location; it is not a content verification. Builds recheck each recorded file.', 'muted')], 'Bind', async () => { const args = { source_id: source.input.value, root: root.input.value }; closeDialog(); await work('bind', args); }); });
async function fileAction(action) { $('file-menu').open = false; const base = S.status?.workspace || '.'; if (action === 'help') {
    dialog('Recovery without this application', [el('p', 'Keep every package with its receipt and members.jsonl.gz manifest, plus the root ARCHIVE.json and RESTORE.py.'), el('pre', 'python RESTORE.py /path/to/archive-set\npython RESTORE.py /path/to/archive-set --to /path/to/new-folder'), el('p', 'Use the Python version specified in the archive recovery instructions; Zstandard packages also require zstd. This preserves ordinary file contents and paths, not complete NTFS or POSIX filesystem semantics.', 'muted')], '', null);
    return;
} if (action === 'doctor') {
    const r = await read('doctor'); S.doctor = r; renderEnvironment();
    const body = el('div');
    for (const check of r.checks || []) {
        const item = el('section', undefined, 'diagnostic');
        item.append(el('h3', `${check.label} · ${check.state.replaceAll('_', ' ')}`), el('p', check.detail));
        if (check.action) item.append(el('p', check.action, 'muted'));
        body.append(item);
    }
    const details = el('details'); details.append(el('summary', 'Exact runtime details'), el('pre', JSON.stringify(r, null, 2))); body.append(details);
    dialog('Runtime and tools', body, '', null);
    return;
} if (action === 'quit') {
    dialog('Quit local service', el('p', 'Active work must finish or be cancelled first. Closing this browser tab alone does not stop the service.'), 'Quit', async () => { await request('/api/stop', {}); serviceStopped = true; clearTimeout(pollingTimer); $('connection-state').textContent = 'Service stopped'; closeDialog(); notice('Service stopped. This tab can be closed.'); });
    return;
} if (action === 'open') {
    const path = field('Existing workspace directory');
    dialog('Open workspace', [path.label, el('p', 'Choose a workspace supported by this release. Use the V12/V13 import command for those older evidence formats.', 'muted')], 'Open', async () => { await activateWorkspace(path.input.value); closeDialog(); notice('Workspace opened.'); });
    return;
} if (action === 'efu') {
    const input = field('Everything export path (.efu / .csv)'), root = field('Original Windows root', 'D:\\'), label = field('Source label', 'Imported drive');
    dialog('Import indexed observations', [input.label, root.label, label.label], 'Import', async () => { const args = { input: input.input.value, root: root.input.value, label: label.input.value }; closeDialog(); await work('import_efu', args, async (r) => { S.scan = r.snapshot_id; S.node = null; view('sources'); await refresh(); }); });
    return;
} if (action === 'legacy') {
    const input = field('Old V12/V13 results directory');
    dialog('Read-only legacy migration', [input.label, el('p', 'Imports scans and supported PAX plan membership. Old workspaces and approvals are not modified or executed; source paths must be rebound.', 'muted')], 'Migrate', async () => { const args = { input: input.input.value }; closeDialog(); await work('migrate', args, r => { dialog('Migration results', el('pre', JSON.stringify(r, null, 2)), '', null); }); });
    return;
} if (action === 'import') {
    const input = field('Input .ap20 evidence file'), output = field('New workspace directory');
    dialog('Import portable evidence', [input.label, output.label, el('p', 'Contains scans and decisions, not original files or archive payloads. Source bindings and destination registrations require explicit review.', 'muted')], 'Import', async () => { const args = { input: input.input.value, output: output.input.value }; closeDialog(); await work('import', args, r => { dialog('Workspace imported', el('p', r.workspace), 'Open imported workspace', async () => { await activateWorkspace(r.workspace); closeDialog(); }); }); });
    return;
} if (action === 'export' || action === 'scan-export') {
    if (action === 'scan-export' && !S.scan)
        throw new Error('Select a recorded scan.');
    const output = field('New output filename', `${base}/exports/${action === 'export' ? 'workspace-' + Date.now() + '.ap20' : S.scan + '.jsonl.gz'}`);
    dialog(action === 'export' ? 'Export workspace evidence' : 'Export full scan listing', [output.label, el('p', 'The complete working evidence remains in SQLite. This is a deliberate additional export, not a payload backup.', 'muted')], 'Export', async () => { const args = action === 'export' ? { output: output.input.value } : { snapshot_id: S.scan, output: output.input.value }; closeDialog(); await work(action === 'export' ? 'export' : 'export_inventory', args, r => notice('Exported: ' + r.path)); });
} }
document.querySelectorAll('[data-file]').forEach(b => b.onclick = safe(() => fileAction(b.dataset.file)));
function renderEnvironment() {
    const r = S.doctor;
    $('environment-summary').textContent = r ? `PAX TAR and gzip ready. ${r.zstd?.path ? 'Zstandard executable found.' : 'Zstandard is optional; install it or choose TAR/gzip.'} ${r.platform.startsWith('Windows') ? 'Check Everything before indexed scanning.' : 'Filesystem acquisition available.'}` : 'Check tools before choosing an optional encoder or scanner.';
}
$('check-tools').onclick = safe(() => fileAction('doctor'));
async function activateWorkspace(path) {
    await request('/api/workspace', { path });
    S.scan = S.scanRecord = S.node = S.parent = null; S.treeOffset = 0;
    selectPlan(null); resetRecoverySearch();
    for (const id of ['scan-list', 'tree-rows', 'tree-pages', 'tree-path', 'scan-summary', 'type-list', 'issue-list', 'build-rows', 'replica-rows']) clear($(id));
    await refresh();
    S.scan = S.scans[0]?.id || null; if (S.scan) await tree();
    selectPlan(S.plans[0]?.id || null); if (S.plan) await packages();
    renderScans(); renderPlanSelector();
}
function progressText(t) {
    const p = t.progress, running = t.state === 'RUNNING';
    const amount = p.unit === 'bytes' ? size(p.done) : p.done.toLocaleString() + ' ' + p.unit;
    const rate = running && p.idle_seconds < 10 && Number.isFinite(p.rate) && p.rate > 0 ? ` · ${p.unit === 'bytes' ? size(p.rate) : p.rate.toLocaleString(undefined, { maximumFractionDigits: 1 }) + ' ' + p.unit}/s` : '';
    const idle = running && p.idle_seconds > 10 ? ' · no new I/O progress ' + duration(p.idle_seconds) : '';
    const cancelled = running && p.cancel_requested ? ' · cancellation requested' : '';
    return `${amount} · elapsed ${duration(p.elapsed_seconds)}${rate}${running ? ' · ETA ' + duration(p.eta_seconds) : ''}${idle}${cancelled}`;
}
function renderProgress(t) { if (!t)
    return; S.active = ['RUNNING', 'QUEUED'].includes(t.state) ? t.id : null; const p = t.progress; $('task-phase').textContent = `${t.state} · ${p.phase}`; $('task-metrics').textContent = progressText(t); const bar = $('task-progress'); if (p.total !== null && p.total > 0) {
    bar.max = p.total;
    bar.value = p.done;
}
else if (S.active)
    bar.removeAttribute('value');
else {
    bar.max = 1;
    bar.value = t.state === 'COMPLETE' ? 1 : 0;
} $('task-path').textContent = t.error?.message || p.path || 'No source reads or writes in progress.'; $('task-path').title = p.path || ''; $('cancel-task').disabled = !S.active || p.cancel_requested; }
$('cancel-task').onclick = safe(async () => { if (S.active)
    await request('/api/cancel', { id: S.active }); });
$('show-activity').onclick = safe(async () => { const tasks = await request('/api/tasks'), body = el('div'); for (const t of tasks.slice().reverse()) {
    body.append(el('h2', `${t.action} · ${t.state}`));
    for (const e of t.progress.events.slice(-8))
        body.append(el('p', `${e.time} ${e.level} ${e.code}${e.path ? ' · ' + e.path : ''}`));
    if (t.error)
        body.append(el('p', t.error.message, 'error'));
} if (!tasks.length)
    body.append(el('p', 'No tasks in this session. Older operations are in Archive → Operation history.')); dialog('Activity', body, '', null); });
function schedulePolling(delay) {
    clearTimeout(pollingTimer);
    if (!serviceStopped) pollingTimer = setTimeout(polling, delay);
}
async function polling() {
    if (pollingBusy || serviceStopped) return;
    pollingBusy = true;
    try {
        const rows = await request('/api/tasks'); S.tasks = rows;
        if ($('connection-state').textContent !== 'Connected') $('connection-state').textContent = 'Connected';
        const active = rows.find(t => t.state === 'RUNNING') || rows.find(t => t.state === 'QUEUED');
        if (active) renderProgress(active); else if (rows.length) renderProgress(rows.at(-1));
        for (const [id, waiter] of waitingTasks) {
            const task = rows.find(t => t.id === id);
            if (!task || !['COMPLETE', 'FAILED', 'CANCELLED'].includes(task.state)) continue;
            const detail = await request('/api/task/' + id);
            waitingTasks.delete(id);
            if (detail.state === 'COMPLETE') waiter.resolve(detail);
            else waiter.reject(new Error(`${detail.error?.code || detail.state}: ${detail.error?.message || 'Operation cancelled'}`));
        }
    } catch (error) {
        if ($('connection-state').textContent !== 'Disconnected · reconnecting') $('connection-state').textContent = 'Disconnected · reconnecting';
        $('connection-state').title = error.message;
    } finally {
        pollingBusy = false;
        schedulePolling(S.active || waitingTasks.size ? 750 : 2500);
    }
}
async function start() {
    const [doctor] = await Promise.all([read('doctor'), refresh()]); S.doctor = doctor; renderEnvironment();
    const pref = S.status.preferences; appearance(pref.appearance || 'system');
    S.scan = pref.selected_snapshot || S.scans[0]?.id || null;
    selectPlan(pref.selected_plan || S.plans[0]?.id || null); view(pref.view || 'sources');
    if (S.scan) await tree(); if (S.plan) await packages();
    renderScans(); renderPlanSelector(); if (S.view === 'archive') await archiveView();
    schedulePolling(0);
}
start().catch(e => notice(e.message, true));
