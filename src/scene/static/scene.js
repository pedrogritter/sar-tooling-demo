/* Report browser failures to the Python process. The page still renders if this file fails. */

(function () {
  function report(message, source) {
    var body = JSON.stringify({
      message: String(message == null ? "" : message),
      source: String(source == null ? "" : source),
    });
    fetch("/client-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body,
    }).catch(function () {
      return undefined;
    });
  }

  window.addEventListener("error", function (event) {
    report(event.message, event.filename);
  });

  window.addEventListener("unhandledrejection", function (event) {
    var reason = event.reason;
    var message = reason && reason.message ? reason.message : reason;
    report(message, "unhandledrejection");
  });
})();
