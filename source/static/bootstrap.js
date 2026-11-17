/* ES5 diagnostic bootstrap. No eval, remote scripts or build-time polyfill bundle.
 * The main interface deliberately targets ES2017; unsupported parsers keep the
 * readable HTML explanation instead of leaving a blank or half-working app.
 */
(function (window, document) {
    'use strict';
    var message = document.getElementById('compatibility-message');
    var panel = document.getElementById('compatibility');
    var shell = document.getElementById('app-shell');
    var loaded = false;

    function fail(text) {
        message.textContent = text;
        panel.hidden = false;
        shell.hidden = true;
    }

    function missingCapabilities() {
        var missing = [];
        var required = {
            'Fetch': typeof window.fetch === 'function',
            'Promises': typeof window.Promise === 'function',
            'Map and Set': typeof window.Map === 'function' && typeof window.Set === 'function',
            'iterators': typeof window.Symbol === 'function' && !!window.Symbol.iterator,
            'Array.from': typeof Array.from === 'function',
            'Array.includes': typeof Array.prototype.includes === 'function',
            'Object.assign': typeof Object.assign === 'function',
            'safe integer checks': typeof Number.isSafeInteger === 'function' && typeof Number.isFinite === 'function' && typeof Number.isInteger === 'function',
            'string prefix checks': typeof String.prototype.startsWith === 'function'
        };
        for (var name in required) {
            if (Object.prototype.hasOwnProperty.call(required, name) && !required[name]) missing.push(name);
        }
        return missing;
    }

    // Small DOM conveniences used by the interface, without changing language
    // syntax or pretending to emulate a missing JavaScript engine.
    if (window.Element && !window.Element.prototype.append) {
        window.Element.prototype.append = function () {
            for (var i = 0; i < arguments.length; i++) {
                this.appendChild(typeof arguments[i] === 'string' ? document.createTextNode(arguments[i]) : arguments[i]);
            }
        };
    }
    if (window.NodeList && !window.NodeList.prototype.forEach) {
        window.NodeList.prototype.forEach = Array.prototype.forEach;
    }

    function enhanceDetails(details) {
        if ('open' in details) return;
        Object.defineProperty(details, 'open', {
            get: function () { return this.hasAttribute('open'); },
            set: function (value) { if (value) this.setAttribute('open', ''); else this.removeAttribute('open'); }
        });
        var summary = details.querySelector('summary');
        if (!summary) return;
        summary.tabIndex = 0;
        summary.setAttribute('role', 'button');
        function toggle() {
            details.open = !details.open;
            summary.setAttribute('aria-expanded', details.open ? 'true' : 'false');
        }
        summary.setAttribute('aria-expanded', details.open ? 'true' : 'false');
        summary.addEventListener('click', toggle);
        summary.addEventListener('keydown', function (event) {
            if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); toggle(); }
        });
    }
    function disclosures(root) {
        Array.prototype.forEach.call(root.querySelectorAll('details'), enhanceDetails);
    }

    window.ArchivistBootstrap = {
        loaded: function () { loaded = true; },
        ready: function () { panel.hidden = true; shell.hidden = false; },
        fail: fail,
        disclosures: disclosures,
        missingCapabilities: missingCapabilities
    };
    var missing = missingCapabilities();
    if (missing.length) {
        fail('This browser cannot run the full interface. Missing capabilities: ' + missing.join(', ') + '. Use a browser with ES2017 support and the listed APIs, or the command-line tools. No operation has been submitted.');
        return;
    }
    disclosures(document);
    var script = document.createElement('script');
    script.src = '/app.js';
    script.onload = function () {
        if (!loaded) fail('The interface could not start. This browser may not parse ES2017 JavaScript, or a local script failed. Use a supported browser or the command line; existing archives remain readable through ARCHIVE.html and RESTORE.py.');
    };
    script.onerror = function () { fail('The local interface script could not be loaded. Keep the Archivist process running, then reload this page. No operation has been submitted by this page.'); };
    document.head.appendChild(script);
}(window, document));
