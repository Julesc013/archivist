/* Behavioral checks of the shipped app.js in a minimal DOM.
 * No browser renderer, CSS or CSP enforcement is simulated or claimed here.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

class Element {
    constructor(tag = 'div') {
        this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
        this.listeners = {}; this.attributes = {}; this.value = ''; this._text = '';
        this.disabled = false; this.hidden = false; this.open = false; this.style = {};
        const names = new Set();
        this.classList = { add: name => names.add(name), toggle: (name, on) => on ? names.add(name) : names.delete(name), contains: name => names.has(name), remove: name => names.delete(name) };
    }
    set textContent(text) { this._text = String(text); this.children = []; if (this.tagName === 'SELECT') this.value = ''; }
    get textContent() { return this._text + this.children.map(c => typeof c === 'string' ? c : c.textContent).join(''); }
    append(...children) { for (const child of children) { if (typeof child !== 'string') { child.parentElement = this; child.ownerDocument = this.ownerDocument; } this.children.push(child); } }
    appendChild(child) { this.append(child); return child; }
    replaceChildren(...children) { this.children = children; this._text = ''; if (this.tagName === 'SELECT') this.value = ''; }
    setAttribute(name, value) { this.attributes[name] = String(value); if (name === 'open') this.open = true; }
    removeAttribute(name) { delete this.attributes[name]; if (name === 'open') this.open = false; }
    hasAttribute(name) { return Object.hasOwn(this.attributes, name); }
    getAttribute(name) { return this.attributes[name] === undefined ? null : this.attributes[name]; }
    contains(node) { return this === node || this.children.some(child => typeof child !== 'string' && child.contains(node)); }
    focus() { if (this.ownerDocument) this.ownerDocument.activeElement = this; }
    getClientRects() { return this.hidden ? [] : [1]; }
    querySelectorAll(selector) {
        const tags = selector.split(',').map(part => part.trim().split(/[:[.]/)[0].toUpperCase()).filter(Boolean);
        return this.children.flatMap(child => typeof child === 'string' ? [] : [...((tags.includes(child.tagName) || selector.includes('[tabindex]') && child.hasAttribute('tabindex')) && !(selector.includes(':not(:disabled)') && child.disabled) ? [child] : []), ...child.querySelectorAll(selector)]);
    }
    querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
    addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
    showModal() { this.setAttribute('open', ''); }
    close() { this.removeAttribute('open'); }
}

function harness() {
    const elements = new Map();
    const node = id => { if (!elements.has(id)) { const element = new Element(id.includes('select') ? 'select' : 'div'); element.ownerDocument = document; elements.set(id, element); document.body.append(element); } return elements.get(id); };
    const requests = []; let respond = null, timerId = 0; const timers = new Map();
    const document = {
        getElementById: node, createElement: tag => { const e = new Element(tag); e.ownerDocument = document; return e; }, createTextNode: text => String(text),
        querySelector: () => ({ content: 'test-token' }),
        querySelectorAll: selector => selector === '#package-rows tr' ? node('package-rows').children : [],
        documentElement: new Element('html'), body: new Element('body'), listeners: {},
        addEventListener(name, listener) { (this.listeners[name] ||= []).push(listener); }
    };
    document.documentElement.ownerDocument = document; document.body.ownerDocument = document; document.documentElement.append(document.body);
    const context = vm.createContext({
        document, console, setTimeout: (fn, ms) => { timers.set(++timerId, { fn, ms }); return timerId; }, clearTimeout: id => timers.delete(id),
        Option: function(text, value) { const option = new Element('option'); option.textContent = text; option.value = value; return option; },
        fetch: async (url, options) => {
            // Initial application boot waits here. Tests exercise actual handlers with controlled API responses.
            if (!respond) return new Promise(() => {});
            requests.push({ url, options });
            const value = await respond(url, options);
            return { ok: true, status: 200, json: async () => value };
        }
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../source/static/app.js'), 'utf8'), context);
    const api = vm.runInContext('({S, selectPlan, packages, members, packageDetail, renderPlanSelector, planLabel, loadList, progressText, polling, waitingTasks, schedulePolling, findRecovery, recoveryArgs, fileAction, tree, work, dialog, closeDialog, renderProgress, reviewSpaces})', context);
    return { api, node, document, requests, timers, respond: fn => { respond = fn; } };
}
function descendants(element, tag) {
    return element.children.flatMap(child => typeof child === 'string' ? [] : [...(child.tagName === tag ? [child] : []), ...descendants(child, tag)]);
}
const fullPackage = { id: 'P000001', kind: 'data', snapshot_id: 'scan-one', anchor: 'Projects', reason: 'WHOLE_DIRECTORY', codec: 'gzip', level: 5, file_count: 1, logical_bytes: 12, estimated_bytes: 16384, status: 'READY' };
const plan = { id: 'plan-one', label: 'Home archive', created: '2026-11-17T08:00:00Z', parent_plan: null, state: 'READY', counts: { packages: 101, files: 101, logical_bytes: 1212, excluded_observations: 0 } };
const readArgs = url => JSON.parse(new URL(url, 'http://localhost').searchParams.get('args') || '{}');
const readAction = url => new URL(url, 'http://localhost').searchParams.get('action');
const records = [];
async function check(name, fn) { await fn(); records.push({ check: name, result: 'PASS' }); }

(async () => {
    await check('Off-page selection opens its actual gzip encoding and level', async () => {
        const h = harness(); Object.assign(h.api.S, { plan: plan.id, package: fullPackage.id, packages: [{ ...fullPackage, id: 'P000101', codec: 'none', level: 3 }] });
        h.respond(url => { assert.equal(readAction(url), 'package'); return fullPackage; });
        await h.node('edit-codec').onclick();
        assert.equal(descendants(h.node('dialog-body'), 'SELECT')[0].value, 'gzip');
        assert.equal(Number(descendants(h.node('dialog-body'), 'INPUT')[0].value), 5);
        assert.equal(h.requests.length, 1);
    });
    await check('Clearing plan removes stale rows, inspector and enabled actions', async () => {
        const h = harness(); Object.assign(h.api.S, { plan: plan.id, package: fullPackage.id, packageRecord: fullPackage, packagePlan: plan.id });
        h.node('package-rows').append(new Element('tr')); h.node('member-rows').append(new Element('tr'));
        h.api.selectPlan(null);
        assert.equal(h.node('package-rows').children.length, 0); assert.equal(h.node('member-rows').children.length, 0);
        assert.equal(h.node('package-name').textContent, 'Select a package'); assert.equal(h.node('edit-codec').disabled, true);
    });
    await check('Move chooser searches compatible packages outside the visible page', async () => {
        const h = harness(); Object.assign(h.api.S, { plan: plan.id, package: fullPackage.id, packageRecord: fullPackage, packagePlan: plan.id, packages: [fullPackage] }); h.api.S.members.add(7);
        h.respond(url => {
            const args = readArgs(url); assert.equal(readAction(url), 'packages'); assert.equal(args.snapshot_id, 'scan-one'); assert.equal(args.exclude_package_id, fullPackage.id); assert.equal(args.kind, 'data');
            return { total: 1, packages: [{ ...fullPackage, id: 'P000101', anchor: 'Other project' }] };
        });
        await h.node('move-members').onclick();
        const options = descendants(h.node('dialog-body'), 'OPTION'); assert(options.some(o => o.value === 'P000101'));
        assert.equal(h.requests.length, 1);
    });
    await check('Selecting a package fetches its member list once', async () => {
        const h = harness(); h.api.selectPlan(plan.id);
        h.respond(url => readAction(url) === 'packages' ? { plan, packages: [fullPackage], total: 1 } : { rows: [{ id: 7, kind: 'file', path: 'Projects/notes.txt', size: 12 }], total: 1 });
        await h.api.packages(); const before = h.requests.length;
        await h.node('package-rows').children[0].onclick();
        const newRequests = h.requests.slice(before); assert.equal(newRequests.length, 1); assert.equal(readAction(newRequests[0].url), 'members');
    });
    await check('Same-label plan revisions have distinct visible identity', async () => {
        const h = harness(); h.api.S.plans = [plan, { ...plan, id: 'plan-two', parent_plan: plan.id }];
        h.api.renderPlanSelector(); const labels = h.node('plan-select').children.map(x => x.textContent);
        assert.notEqual(labels[1], labels[2]); assert(labels[1].includes('plan-one')); assert(labels[2].includes('plan-two'));
    });
    await check('Older object pages remain reachable beyond 100 records', async () => {
        const h = harness(); h.respond(url => { const args = readArgs(url); return Array.from({ length: args.offset ? 1 : 100 }, (_, i) => ({ id: 'scan-' + (args.offset + i) })); });
        await h.api.loadList('scans'); assert.equal(h.node('scan-load-more').hidden, false);
        await h.api.loadList('scans', true); assert.equal(h.api.S.scans.length, 101); assert.equal(h.node('scan-load-more').hidden, true);
        assert.equal(readArgs(h.requests[1].url).offset, 100);
    });
    await check('Terminal progress never reports an active stall or ETA; running throughput is shown', async () => {
        const h = harness(), progress = { unit: 'bytes', done: 1024, elapsed_seconds: 5, idle_seconds: 45, rate: 1024, eta_seconds: null, cancel_requested: false };
        const finished = h.api.progressText({ state: 'COMPLETE', progress }); assert(!finished.includes('no new I/O')); assert(!finished.includes('ETA'));
        const running = h.api.progressText({ state: 'RUNNING', progress: { ...progress, idle_seconds: 1 } }); assert(running.includes('/s'));
    });
    await check('Task polling fetches a terminal result once and resolves its waiter', async () => {
        const h = harness(); let resolved = null; const task = { id: 'task-1', state: 'COMPLETE', progress: { phase: 'Done', unit: 'items', done: 1, total: 1, elapsed_seconds: 1, eta_seconds: null, idle_seconds: 0 } };
        h.api.waitingTasks.set(task.id, { resolve: value => { resolved = value; }, reject: error => { throw error; } });
        h.respond(url => url === '/api/tasks' ? [task] : { ...task, result: { ok: true } });
        await h.api.polling(); assert.equal(resolved.result.ok, true); assert.equal(h.api.waitingTasks.size, 0); assert.equal(h.requests.length, 2);
    });
    await check('Connection errors keep pending work pending and show reconnect status', async () => {
        const h = harness(); h.api.waitingTasks.set('task-1', {}); h.respond(() => { throw new Error('connection lost'); });
        await h.api.polling(); assert.equal(h.api.waitingTasks.size, 1); assert(h.node('connection-state').textContent.includes('reconnecting'));
        assert.equal(h.requests.length, 1);
    });
    await check('Recovery lookup selects full matched packages and required directory metadata explicitly', async () => {
        const h = harness(); h.node('recover-source').value = '/archive'; h.node('recover-query').value = 'notes';
        h.respond(() => ({ total: 1, rows: [{ path: 'Projects/notes.txt', package_id: 'P000001', size: 12 }], package_ids: ['P000001', 'P000002'], metadata_completeness: 'complete', payload_verified: false }));
        await h.api.findRecovery(); assert.equal(h.api.S.recoveryPackages, null);
        await h.node('use-recovery-matches').onclick();
        assert.equal(JSON.stringify(h.api.recoveryArgs().packages), JSON.stringify(['P000001', 'P000002']));
        assert(h.node('recovery-selection').textContent.includes('Other members'));
        h.node('recover-source').value = '/other'; assert.throws(() => h.api.recoveryArgs(), /Archive set changed/);
    });
    await check('Partial recovery kits report missing or unknown directory metadata honestly', async () => {
        for (const completeness of ['missing', 'unknown']) {
            const h = harness(); h.node('recover-source').value = '/partial'; h.node('recover-query').value = 'notes';
            h.respond(() => ({ total: 1, rows: [{ path: 'Projects/notes.txt', package_id: 'P000001', size: 12 }], package_ids: ['P000001'], metadata_completeness: completeness, missing_metadata_package_ids: completeness === 'missing' ? ['P000002'] : [], payload_verified: false }));
            await h.api.findRecovery(); await h.node('use-recovery-matches').onclick();
            const displayed = h.node('recovery-selection').textContent;
            assert(!displayed.includes('Required directory metadata is available'));
            assert(displayed.includes(completeness === 'missing' ? 'P000002' : 'unknown'));
            assert.equal(JSON.stringify(h.api.recoveryArgs().packages), JSON.stringify(['P000001']));
        }
    });
    await check('Media fit keeps native input explicit and reports missing metadata despite byte fit', async () => {
        const h = harness(); h.api.S.plan = plan.id;
        h.node('media-preset').value = '12000'; h.node('media-preset').onchange();
        assert.equal(h.node('media-capacity').value, '12000');
        h.node('media-count').value = '1'; h.node('media-reserve').value = '5';
        h.respond(url => {
            assert.equal(readAction(url), 'allocate');
            const args = readArgs(url); assert.equal(args.media[0].capacity, 12000000000000);
            return {media: [{...args.media[0], used: 1000, packages: ['P000001'], missing_metadata_package_ids: ['P000002']}],
                unallocated: [], measurement: {basis: 'measured'}, metadata_dependencies_complete: false, basis: 'Measured package objects'};
        });
        await h.node('fit-media').onclick();
        const text = h.node('allocation-results').textContent;
        assert(text.includes('P000002')); assert(text.includes('does not yet have a complete recovery selection'));
        assert(text.includes('Size basis: measured')); assert(!text.includes('All package estimates fit'));
    });
    await check('Diagnostics show actionable checks before optional exact details', async () => {
        const h = harness(); h.respond(() => ({ platform: 'Linux', zstd: { path: null }, checks: [{ label: 'Zstandard', state: 'missing', detail: 'Not on PATH', action: 'Choose TAR or install zstd.' }] }));
        await h.api.fileAction('doctor'); assert(h.node('dialog-body').textContent.includes('Choose TAR or install zstd.'));
        assert.equal(descendants(h.node('dialog-body'), 'DETAILS').length, 1);
    });
    await check('Repeated work submission is single-flight and a failed view callback cannot erase completion', async () => {
        const h = harness(); let callbacks = 0;
        const task = { id: 'one-job', action: 'verify', state: 'COMPLETE', progress: { phase: 'Done', unit: 'items', done: 1, total: 1, elapsed_seconds: 1, eta_seconds: null, idle_seconds: 0 }, result: { state: 'VERIFIED' } };
        h.respond(url => {
            if (url === '/api/task') return { task_id: task.id };
            if (url === '/api/tasks') return [task];
            if (url === '/api/task/' + task.id) return task;
            return readAction(url) === 'status' ? { workspace: '/workspace', version: 'test' } : [];
        });
        const callback = () => { callbacks++; throw new Error('view render failed'); };
        const first = h.api.work('verify', { bundle: '/archive' }, callback);
        const second = h.api.work('verify', { bundle: '/archive' }, callback);
        assert.equal(first, second);
        await new Promise(resolve => setImmediate(resolve));
        await h.api.polling();
        const result = await first;
        assert.equal(result.state, 'VERIFIED'); assert.equal(callbacks, 1);
        assert.equal(h.requests.filter(r => r.url === '/api/task').length, 1);
        assert(h.node('notice').textContent.includes('completed, but'));
    });
    await check('Duplicate modal submissions call the handler only once', async () => {
        const h = harness(); let calls = 0, release;
        h.api.dialog('Test submission', new Element('p'), 'Submit', () => { calls++; return new Promise(resolve => { release = resolve; }); });
        const submit = h.node('dialog-form').listeners.submit[0];
        const first = submit({ preventDefault() {} }); const second = submit({ preventDefault() {} });
        assert.equal(calls, 1); assert.equal(h.node('dialog-submit').disabled, true);
        release(); await Promise.all([first, second]); assert.equal(h.node('dialog-submit').disabled, false);
    });
    await check('Dialog fallback traps focus, handles Escape and returns focus', async () => {
        const h = harness(), opener = h.node('new-scan'); opener.focus();
        h.node('dialog').showModal = undefined; h.node('dialog').close = undefined;
        for (const id of ['dialog-close', 'dialog-cancel', 'dialog-submit']) { h.node(id).tagName = 'BUTTON'; h.node(id).tabIndex = 0; h.node('dialog').append(h.node(id)); }
        h.node('dialog').append(h.node('dialog-body'));
        h.api.dialog('Fallback', new Element('p'), 'Continue', () => {});
        h.node('dialog-submit').focus();
        h.document.listeners.keydown[0]({ key: 'Tab', shiftKey: false, preventDefault() {} });
        assert.equal(h.document.activeElement, h.node('dialog-close'));
        h.document.listeners.keydown[0]({ key: 'Tab', shiftKey: true, preventDefault() {} });
        assert.equal(h.document.activeElement, h.node('dialog-submit'));
        assert(h.node('dialog').hasAttribute('open')); assert.equal(h.node('dialog-backdrop').hidden, false);
        assert.equal(h.node('app-shell').getAttribute('aria-hidden'), 'true');
        h.document.listeners.keydown[0]({ key: 'Escape', preventDefault() {} });
        assert(!h.node('dialog').hasAttribute('open')); assert.equal(h.node('dialog-backdrop').hidden, true);
        assert.equal(h.document.activeElement, opener);
    });
    await check('An older directory response cannot overwrite a newer selection in the same scan', async () => {
        const h = harness(), pending = {};
        Object.assign(h.api.S, { scan: 'scan-one', node: 1, scans: [{ id: 'scan-one', counts: { issues: 0 } }] });
        h.respond(url => {
            const action = readAction(url), args = readArgs(url);
            if (action === 'browse') return new Promise(resolve => { pending[args.node_id] = resolve; });
            return action === 'types' ? { total: 0, rows: [] } : [];
        });
        const older = h.api.tree(); h.api.S.node = 2; const newer = h.api.tree();
        const response = (id, path) => ({ directory: { id, parent: 0, path }, rows: [], total: 0, scan: { id: 'scan-one', backend: 'fixture', counts: { eligible_files: 0, excluded: 0, errors: 0 } } });
        pending[2](response(2, 'newer')); await newer;
        pending[1](response(1, 'older')); await older;
        assert.equal(h.node('tree-path').textContent, 'newer'); assert.equal(h.api.S.node, 2);
    });
    await check('Missing task records terminate waiters after successful reconnection without resubmission', async () => {
        const h = harness(); let rejection;
        h.api.waitingTasks.set('lost-task', { resolve() {}, reject: error => { rejection = error; } });
        h.respond(() => []);
        await h.api.polling(); await h.api.polling(); assert.equal(rejection, undefined);
        await h.api.polling(); assert(rejection.message.includes('No operation was resubmitted'));
        assert.equal(h.api.waitingTasks.size, 0); assert(h.requests.every(r => r.url === '/api/tasks'));
    });
    await check('Changed authentication session stops retries and asks for reload', async () => {
        const h = harness(); let rejection;
        h.api.waitingTasks.set('old-task', { resolve() {}, reject: error => { rejection = error; } });
        h.respond(() => ({ error: { code: 'TOKEN', message: 'Session changed' } }));
        await h.api.polling(); assert(rejection.message.includes('session changed'));
        assert(h.node('connection-state').textContent.includes('reload')); assert.equal(h.api.waitingTasks.size, 0);
    });
    await check('Overall package counts stay distinct from active byte progress', async () => {
        const h = harness();
        h.api.renderProgress({ id: 't', action: 'build', state: 'RUNNING', progress: { phase: 'Hash package', unit: 'bytes', done: 200, total: 1000, elapsed_seconds: 10, idle_seconds: 0, overall: { done: 1, total: 3, unit: 'packages' }, package: { id: 'P000002', index: 2, total: 3 } } });
        assert(h.node('task-overall').textContent.includes('1 of 3 packages'));
        assert(h.node('task-package').textContent.includes('2 of 3'));
        assert.equal(h.node('task-progress').value, 200); assert.equal(h.node('task-overall-progress').value, 1);
    });
    await check('Build review explains retained staging separately from a later destination copy', async () => {
        const h = harness(), panel = h.api.reviewSpaces('build', { output: '/staging', estimated_required_bytes: 4096, free_bytes: 8192, capacity_breakdown: { basis: 'Remaining retained packages' } });
        assert(panel.textContent.includes('Staging · retained archive set'));
        assert(panel.textContent.includes('Final destination · separate copy'));
        assert(panel.textContent.includes('not just the largest package'));
    });
    console.log(JSON.stringify({ method: 'Shipped JavaScript handlers in a minimal DOM; not browser/CSS/CSP qualification', checks: records, count: records.length }, null, 2));
})().catch(error => { console.error(error); process.exitCode = 1; });
