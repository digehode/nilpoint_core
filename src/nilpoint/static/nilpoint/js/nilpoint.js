/* Nilpoint UI behaviour.
 *
 * htmx swaps are wrapped in the browser's View Transitions API (when
 * available) so panels cross-fade their content and morph between their old
 * and new boxes instead of snapping. Which elements take part is decided in
 * CSS via view-transition-name.
 *
 * Diagnostics: the console gets a [nilpoint] line on load saying which method
 * is active. Set window.__nilpointVerbose = true in the console to also log
 * every swap that starts a view transition.
 */
(() => {
    var FALLBACK_DURATION_MS = 350;

    function log() {
        if (!window.console || !console.info) {
            return;
        }
        var args = Array.prototype.slice.call(arguments);
        args.unshift("[nilpoint]");
        console.info.apply(console, args);
    }

    if (!window.htmx) {
        log("htmx not found - panel transitions disabled");
        return;
    }

    // htmx wraps each swap in a View Transition but ignores the returned
    // promises. When one panel's swap starts a transition while another is
    // still running, the browser skips the older one and rejects its
    // promises with "AbortError: Transition was skipped" - harmless, but
    // noisy in the console. Silence just that rejection.
    window.addEventListener("unhandledrejection", (event) => {
        var reason = event.reason;
        if (
            reason &&
            reason.name === "AbortError" &&
            /Transition was skipped/.test(reason.message || "")
        ) {
            event.preventDefault();
            if (window.__nilpointVerbose) {
                log("view transition skipped (a newer swap started)");
            }
        }
    });

    var supportsViewTransitions =
        typeof document.startViewTransition === "function";
    var reducedMotion =
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    window.htmx.config.globalViewTransitions = supportsViewTransitions;

    function transitionDuration() {
        var value = getComputedStyle(document.documentElement).getPropertyValue(
            "--nilpoint-transition-duration",
        );
        var ms = parseFloat(value);
        return isNaN(ms) ? FALLBACK_DURATION_MS : ms;
    }

    var duration = transitionDuration();

    log(
        "htmx " +
            window.htmx.version +
            " | View Transitions: " +
            (supportsViewTransitions ? "supported" : "unsupported") +
            " | panel transitions: " +
            (supportsViewTransitions && !reducedMotion
                ? "on (" + duration + "ms)"
                : "off") +
            " | motion: " +
            (reducedMotion ? "reduced" : "normal"),
    );

    window.htmx.on("htmx:beforeTransition", (event) => {
        if (!window.__nilpointVerbose) {
            return;
        }
        var elt = event.detail && event.detail.elt;
        log("view transition:", (elt && (elt.id || elt.tagName)) || "document");
    });
})();
