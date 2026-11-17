/* Shipped ES5 bootstrap behavior with controlled capabilities, not a browser. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../source/static/bootstrap.js'), 'utf8');

function harness(overrides = {}) {
    const nodes = { compatibility: { hidden: false }, 'compatibility-message': { textContent: '' }, 'app-shell': { hidden: true } };
    const scripts = [];
    function Element() { this.children = []; }
    Element.prototype.appendChild = function (child) { this.children.push(child); };
    function NodeList() {}
    const attributes = {}, listeners = {}, summary = { setAttribute(name, value) { this[name] = value; }, addEventListener(name, fn) { listeners[name] = fn; } };
    const details = {
        hasAttribute(name) { return Object.hasOwn(attributes, name); },
        setAttribute(name, value) { attributes[name] = value; },
        removeAttribute(name) { delete attributes[name]; },
        querySelector() { return summary; }
    };
    const document = {
        getElementById: id => nodes[id],
        createElement: tag => ({ tag }),
        createTextNode: text => ({ textContent: text }),
        querySelectorAll: () => [details],
        head: { appendChild: script => scripts.push(script) }
    };
    const window = Object.assign({ fetch() {}, Promise, Map, Set, Symbol, Element, NodeList }, overrides);
    vm.runInNewContext(source, { window, document });
    return { nodes, scripts, window, details, summary, listeners };
}

const checks = [];
function check(name, fn) { fn(); checks.push({ check: name, result: 'PASS' }); }
check('Missing Fetch and Promises prevent application loading with readable guidance', () => {
    const h = harness({ fetch: undefined, Promise: undefined });
    assert.equal(h.scripts.length, 0);
    assert(h.nodes['compatibility-message'].textContent.includes('Fetch'));
    assert(h.nodes['compatibility-message'].textContent.includes('Promises'));
    assert.equal(h.nodes['app-shell'].hidden, true);
    assert.equal(h.nodes.compatibility.hidden, false);
});
check('Only a successful app startup reveals the interactive workspace', () => {
    const h = harness();
    assert.equal(h.scripts.length, 1); assert.equal(h.scripts[0].src, '/app.js');
    h.window.ArchivistBootstrap.loaded(); h.scripts[0].onload();
    assert.equal(h.nodes['app-shell'].hidden, true);
    h.window.ArchivistBootstrap.ready();
    assert.equal(h.nodes['app-shell'].hidden, false); assert.equal(h.nodes.compatibility.hidden, true);
});
check('Failed parsing or script loading retains actionable offline recovery guidance', () => {
    const parse = harness(); parse.scripts[0].onload();
    assert(parse.nodes['compatibility-message'].textContent.includes('ES2017'));
    assert(parse.nodes['compatibility-message'].textContent.includes('ARCHIVE.html'));
    const load = harness(); load.scripts[0].onerror();
    assert(load.nodes['compatibility-message'].textContent.includes('Keep the Archivist process running'));
    assert.equal(load.nodes['app-shell'].hidden, true);
});
check('Small DOM fallbacks preserve text append and disclosure keyboard operation', () => {
    const h = harness(), node = new h.window.Element(), child = new h.window.Element();
    node.append('literal text', child);
    assert.equal(node.children[0].textContent, 'literal text'); assert.equal(node.children[1], child);
    const collection = Object.assign(new h.window.NodeList(), { 0: 'one', 1: 'two', length: 2 }), values = [];
    collection.forEach(value => values.push(value)); assert.deepEqual(values, ['one', 'two']);
    assert.equal(h.details.open, false);
    h.listeners.keydown({ key: 'Enter', preventDefault() {} });
    assert.equal(h.details.open, true); assert.equal(h.summary['aria-expanded'], 'true');
    h.listeners.click(); assert.equal(h.details.open, false);
});
console.log(JSON.stringify({ method: 'Controlled-capability execution of the shipped bootstrap; no browser rendering or historical-engine qualification', checks, count: checks.length }, null, 2));
