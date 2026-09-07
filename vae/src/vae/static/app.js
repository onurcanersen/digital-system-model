/* VAE console. Three independent stages, each owning its own credentials:
 *
 *   1. sign-in  — the LDAP directory only. Knows nothing about the sources.
 *   2. sources  — one tile per data source, each opening a modal for that
 *                 source's connection details. Addresses are prefilled from
 *                 config.ini; credentials are the source's own, asked once
 *                 per session. The sources are peers: either order works,
 *                 and connecting one leaves the other alone.
 *   3. context  — project / platform / version, read over the config-mgmt-DB
 *                 connection.
 *
 * Nothing is remembered in the browser except usernames, for prefill. What
 * survives a refresh lives on the server: Flask's session cookie holds
 * username/role/conn_token/selection plus the UI record below, and the open
 * connections live in Components.connections under that token — so boot is a
 * single GET /api/session that decides which stage to resume at. A server
 * restart drops the in-memory connections, and the sources stage is entered
 * again.
 *
 * The UI record is where the user was standing: the card, the produced file
 * the Model card was showing, and a candidate chosen but not yet run. This
 * page has no addresses of its own — one card is shown at a time and nothing
 * is in the URL — so that record is what a reload reads instead of a path.
 */
(function () {
  "use strict";

  var API = {
    session: "/api/session",
    login: "/api/login",
    logout: "/api/logout",
    ui: "/api/session/ui",
    selection: "/api/selection",
    projects: "/api/projects",
    units: "/api/units/",
    run: "/api/msd/run",
    tasks: "/api/msd/tasks/"
  };

  /* The versions a unit's source repository publishes — the set a candidate
   * version is chosen from (SRS DSM-MSD req 11). Not scoped by the selection:
   * a candidate is precisely a version no system version defines yet. */
  function unitVersionsUrl(unitName) {
    return API.units + encodeURIComponent(unitName) + "/versions";
  }

  function taskUrl(taskId, suffix) {
    return API.tasks + encodeURIComponent(taskId) + "/" + suffix;
  }

  /* Produced Model Setup Data files are addressed by the selection they
   * describe plus the id of the run that produced them — not by a task id
   * the server can forget. A run's execution record expires; the file it
   * wrote does not, so this is what keeps an old file openable. */
  function msdFilesUrl(selection, runId, suffix) {
    var base =
      API.projects +
      "/" + encodeURIComponent(selection.project_id) +
      "/platforms/" + encodeURIComponent(selection.platform_id) +
      "/versions/" + encodeURIComponent(selection.version_id) +
      "/msd-files";
    return runId ? base + "/" + encodeURIComponent(runId) + "/" + suffix : base;
  }

  /* The data sources this session must hold a connection to. One entry drives
   * the tile, the modal's header, the address prefill, the endpoint and the
   * username remembered for next time. `flag` is the field GET /api/session
   * reports that connection under. */
  var SOURCES = [
    {
      key: "config_mgmt_db",
      name: "CMDB Data",
      title: "Configuration Management DB",
      icon: "lucide-database",
      endpoint: "/api/data-sources/connect/config-mgmt-db",
      flag: "config_mgmt_db_connected",
      userKey: "vae.last-db-username"
    },
    {
      key: "source_code_repo",
      name: "SW Units & Scripts",
      title: "Source Code Repository",
      icon: "lucide-file-code",
      endpoint: "/api/data-sources/connect/source-code-repo",
      flag: "source_code_repo_connected",
      userKey: "vae.last-repo-username"
    }
  ];

  // Per-card header. Cards about the product carry the product's name; a
  // card about one thing names that thing and shows its glyph.
  var HEADERS = {
    boot: { subtitle: "Restoring" },
    login: { logo: true, subtitle: "Secure Access" },
    sources: {
      title: "Data Sources",
      icon: "lucide-hard-drive",
      subtitle: "Connect Sources"
    },
    select: {
      title: "Project Context",
      icon: "lucide-network",
      subtitle: "Select Scope"
    },
    // No subtitle: the context strip under the title already says what this
    // inventory is for, better than a line of prose could.
    inventory: {
      title: "Software Unit Inventory",
      icon: "lucide-package"
    },
    // What has already been produced for this context — the card the Produce
    // stage opens on, so an existing file is offered before a run is spent
    // making another (SRS DSM-VAE req 5).
    files: {
      title: "Model Setup Data",
      icon: "lucide-file-code",
      subtitle: "Produced Files"
    },
    // No glyph: the panel bar's rocket is driven by the run's state and is the
    // only one on this card that means anything — a second, larger copy of it
    // costs the console 76px and says less.
    run: {
      title: "Model Setup Data",
      subtitle: "Production Run"
    },
    // No glyph and no subtitle: the context strip under the title already
    // says which model these panels are describing, and the deck below is
    // tight enough for the screen without a line of prose above it.
    model: {
      title: "Core System Model"
    }
  };

  var PRODUCT_TITLE = "Digital System Model";

  // Which stage each card belongs to, for the stepper above the card. Boot
  // and sign-in have no stage — the stepper is what comes after signing in.
  var STAGES = ["sources", "select", "inventory", "run", "model"];
  // The Produce stage owns two cards — the files already produced, and the
  // console of a run producing another — so both map to the same stage.
  var STAGE_OF = {
    sources: { index: 0, complete: false },
    select: { index: 1, complete: false },
    inventory: { index: 2, complete: false },
    files: { index: 3, complete: false },
    run: { index: 3, complete: false },
    model: { index: 4, complete: false }
  };

  var VIEWS = [
    "boot",
    "login",
    "sources",
    "select",
    "inventory",
    "files",
    "run",
    "model"
  ];

  // Views that show the signed-in footer. Card width is not listed here: the
  // stylesheet reads the data-view attribute set below and picks one of its
  // three steps from it.
  var WITH_SESSIONBAR = {
    sources: true,
    select: true,
    inventory: true,
    files: true,
    run: true,
    model: true
  };

  // Celery states the run can end in, and how each reads on the card.
  var RUN_STATES = {
    PENDING: { label: "Queued", tone: "busy" },
    RETRY: { label: "Retrying", tone: "busy" },
    STARTED: { label: "Running", tone: "busy" },
    SUCCESS: { label: "Successful", tone: "ok" },
    FAILURE: { label: "Failed", tone: "bad" },
    REVOKED: { label: "Cancelled", tone: "bad" }
  };
  var RUN_TERMINAL = { SUCCESS: true, FAILURE: true, REVOKED: true };

  var LAST_USER_KEY = "vae.last-username";

  var state = {
    username: null,
    defaults: null,
    // Per source key: does the server hold that connection for this session.
    sources: {},
    selection: null,
    // Every version the current project/platform publishes, as the database
    // returned them — the raw rows behind the version picker, which the
    // context strip reads for the plain label and the effective-version flag.
    versions: null,
    // Where the user was standing, as the server last recorded it —
    // {view, model_file, candidate}. Read once on boot to choose the card to
    // resume on; `rememberUi` keeps the server's copy in step after that.
    ui: null,
    // The run this session is tracking, as the server last described it —
    // {task_id, project_id, platform_id, version_id, submitted_at} — so a
    // reload re-attaches to a run already in flight.
    activeTask: null,
    // The software unit version being evaluated for installation, as
    // {unit_name, version}, or null for a run of the versions this system
    // version defines (SRS DSM-MSD req 11). Chosen on the Inventory stage and
    // sent with the run; belongs to the selection, so a change of selection
    // clears it.
    candidate: null,
    // Every Model Setup Data file produced for the current selection, as the
    // server last listed them (newest first). Null until the Produce card has
    // asked; [] means the selection has produced none.
    files: null,
    // The produced file the Model card is showing — {run_id, produced_by,
    // generated_at, ...} out of `files`, or the run that just succeeded — and
    // that file once read. The model card's only precondition, and its cache,
    // so stepping back and forth between Produce and Model does not refetch it.
    modelFile: null,
    model: null,
    view: "boot"
  };

  var el = {};

  function $(id) {
    return document.getElementById(id);
  }

  /* ---------------------------------------------------------------- http */

  function request(method, url, body) {
    var options = { method: method, credentials: "same-origin" };
    if (body !== undefined) {
      options.headers = { "Content-Type": "application/json" };
      options.body = JSON.stringify(body);
    }
    return fetch(url, options).then(function (response) {
      if (response.status === 204) {
        return null;
      }
      return response
        .json()
        .catch(function () {
          return {};
        })
        .then(function (payload) {
          if (!response.ok) {
            var error = new Error(
              payload.error || "Request failed (" + response.status + ")."
            );
            error.status = response.status;
            throw error;
          }
          return payload;
        });
    });
  }

  // A 401 means the server no longer accepts this session; there is nothing
  // to salvage locally, so start over at sign-in.
  function handleExpired(error) {
    if (error.status !== 401) {
      return false;
    }
    resetState();
    closeModal();
    showView("login");
    setMessage("login", "error", "Session expired. Sign in again.");
    return true;
  }

  /* --------------------------------------------------------------- views */

  function showView(name) {
    // The card being left still has its scroll position; a hidden one does
    // not, so it is taken here rather than after the switch.
    if (state.view === "inventory" && name !== "inventory") {
      keepInventoryScroll();
    }
    state.view = name;
    VIEWS.forEach(function (view) {
      $("view-" + view).hidden = view !== name;
    });
    renderHeader(HEADERS[name]);
    renderStepper(name);
    // What the stylesheet keys the card's width and content floor off.
    el.card.setAttribute("data-view", name);
    // The run card is sized by the viewport rather than by its content: the
    // shell widens to it and stops height-centring, so the console below can
    // take every row the chrome does not.
    el.shell.classList.toggle("shell--run", name === "run");
    // The model card is wider still, but sized by its own panels: it scrolls
    // the page rather than fitting the viewport, so it takes the width alone.
    el.shell.classList.toggle("shell--model", name === "model");
    renderSessionbar(!!WITH_SESSIONBAR[name]);

    var focusTarget = {
      login: el.username,
      sources: el.sourcesGrid.querySelector(".source__tile"),
      select: el.project
    }[name];
    if (focusTarget && !focusTarget.disabled) {
      focusTarget.focus();
    }
    // Every card change passes through here, and so does every change of the
    // file on show — openFile ends on the model card.
    rememberUi();
  }

  function renderStepper(name) {
    var stage = STAGE_OF[name];
    el.stepperList.hidden = !stage;
    if (!stage) {
      return;
    }
    STAGES.forEach(function (key, index) {
      var drawn = "todo";
      if (index < stage.index || (index === stage.index && stage.complete)) {
        drawn = "done";
      } else if (index === stage.index) {
        drawn = "current";
      }
      el.stepper[key].item.setAttribute("data-state", drawn);
      // Reachability is not the drawn state: the sources stage is always open
      // once signed in, the context stage as soon as every source is
      // connected, the inventory stage once a context is confirmed, and the
      // model stage once a run has produced a file — including while
      // standing on an earlier card.
      var scoped = allConnected() && !!state.selection;
      var reachable =
        key === "sources" ||
        (key === "select" && allConnected()) ||
        ((key === "inventory" || key === "run") && scoped) ||
        (key === "model" && scoped && !!state.modelFile);
      el.stepper[key].button.disabled = !reachable;
    });
  }

  function renderHeader(header) {
    el.title.textContent = header.title || PRODUCT_TITLE;
    el.subtitle.textContent = header.subtitle || "";
    el.subtitle.hidden = !header.subtitle;
    el.logo.hidden = !header.logo;
    el.brandIcon.hidden = !header.icon;
    if (header.icon) {
      el.brandIcon.className = "lucide " + header.icon + " brand-icon";
    }
  }

  function renderSessionbar(visible) {
    el.sessionbar.hidden = !visible;
    if (!visible) {
      return;
    }
    el.sessionbarUser.textContent = state.username || "";
  }

  /* ------------------------------------------------------------ messages */

  // kind: "ok" | "info" | anything else (error). An empty text clears the
  // strip entirely. "info" is a calm, neutral notice (a reconnection in
  // flight) — it must not read as an error.
  function setMessage(view, kind, text) {
    var node = $(view + "-message");
    if (!node) {
      return;
    }
    node.className =
      kind === "ok"
        ? "message message--ok"
        : kind === "info"
        ? "message message--info"
        : "message";
    node.textContent = "";
    if (!text) {
      return;
    }
    var icon = document.createElement("i");
    icon.className =
      kind === "ok"
        ? "lucide lucide-circle-check"
        : kind === "info"
        ? "lucide lucide-network"
        : "lucide lucide-triangle-alert";
    var body = document.createElement("span");
    // textContent, not innerHTML: server error strings are data, not markup.
    body.textContent = text;
    node.appendChild(icon);
    node.appendChild(body);
  }

  function setBusy(button, busy, busyLabel, restLabel) {
    button.disabled = busy;
    var label = button.querySelector(".submit__label");
    if (!label) {
      return;
    }
    label.textContent = "";
    if (busy) {
      var spinner = document.createElement("span");
      spinner.className = "spinner";
      label.appendChild(spinner);
    }
    label.appendChild(document.createTextNode(busy ? busyLabel : restLabel));
  }

  function clearOnInput(inputs, view) {
    inputs.forEach(function (input) {
      input.addEventListener("input", function () {
        if ($(view + "-message").textContent) {
          setMessage(view, null, "");
        }
      });
    });
  }

  /* ------------------------------------------------------------- session */

  function adopt(session) {
    state.username = session.username;
    state.defaults = session.defaults;
    SOURCES.forEach(function (source) {
      state.sources[source.key] = !!session[source.flag];
    });
    state.selection = session.selection || null;
    // A run describes the context it was submitted for. The server keeps
    // tracking it across a change of context, so one that no longer matches
    // is not this session's run to show.
    state.activeTask = tracks(session.active_task, state.selection)
      ? session.active_task
      : null;
    state.ui = session.ui || null;
    // A reload lands on the run already in flight, so the candidate it is
    // evaluating comes back with it (SRS DSM-MSD req 11) — a submitted run is
    // the authority on what it is evaluating, over anything chosen since.
    // Failing that, the choice the user had made but not yet run.
    state.candidate = state.activeTask
      ? state.activeTask.candidate || null
      : (state.ui && state.ui.candidate) || null;
  }

  function tracks(task, selection) {
    return (
      !!task &&
      !!selection &&
      task.project_id === selection.project_id &&
      task.platform_id === selection.platform_id &&
      task.version_id === selection.version_id
    );
  }

  function resetState() {
    state.username = null;
    SOURCES.forEach(function (source) {
      state.sources[source.key] = false;
    });
    state.selection = null;
    state.versions = null;
    state.activeTask = null;
    state.ui = null;
    candidateVersions = {};
    forgetContext();
    // The next sign-in starts a session of its own: nothing this one told the
    // server about where it stood applies to it.
    lastUi = null;
    closeRunStream();
  }

  /* The UI record as the server last heard it, so an unchanged one is not
   * re-sent — every card change goes through showView, and most of them say
   * nothing new. */
  var lastUi = null;

  /* Tell the server where the user is standing, so a reload can put them back
   * (SRS DSM-VAE req 5: the file selected for use survives with it). Sent and
   * forgotten: this is bookkeeping alongside the navigation, never a step in
   * it, so a failed write leaves the UI exactly where the user put it and
   * costs at most a stale resume. A 401 is the one answer worth acting on,
   * and handleExpired takes the session back to sign-in. */
  function rememberUi() {
    if (state.view === "boot" || state.view === "login") {
      return;
    }
    var record = {
      view: state.view,
      model_file: state.modelFile ? state.modelFile.run_id : null,
      candidate: state.candidate || null
    };
    var sent = JSON.stringify(record);
    if (sent === lastUi) {
      return;
    }
    lastUi = sent;
    request("POST", API.ui, record).catch(function (error) {
      // Say it again next time rather than trusting a write that failed.
      lastUi = null;
      handleExpired(error);
    });
  }

  function allConnected() {
    return SOURCES.every(function (source) {
      return state.sources[source.key];
    });
  }

  function signOut() {
    request("POST", API.logout)
      .catch(function () {
        // Even if the server never heard it, drop everything locally.
      })
      .then(function () {
        resetState();
        closeModal();
        el.loginForm.reset();
        el.sourcePassword.value = "";
        restore(el.username, LAST_USER_KEY);
        showView("login");
      });
  }

  function boot() {
    request("GET", API.session)
      .then(function (session) {
        if (!session.authenticated) {
          restore(el.username, LAST_USER_KEY);
          showView("login");
          return;
        }
        adopt(session);
        if (!allConnected()) {
          enterSources();
          return;
        }
        resumeContext();
      })
      .catch(function () {
        restore(el.username, LAST_USER_KEY);
        showView("login");
        setMessage("login", "error", "Unable to reach the server.");
      });
  }

  /* ------------------------------------------------------------- sources */

  function enterSources() {
    setMessage("sources", null, "");
    renderSources();
    showView("sources");
  }

  // One tile per source, rebuilt after every connect so the state line and
  // the Continue button never drift from `state.sources`.
  function renderSources() {
    el.sourcesGrid.textContent = "";
    SOURCES.forEach(function (source) {
      var connected = !!state.sources[source.key];

      var icon = document.createElement("i");
      icon.className = "lucide " + source.icon + " source__icon";

      var name = document.createElement("span");
      name.className = "source__name";
      name.textContent = source.name;

      var tile = document.createElement("button");
      tile.type = "button";
      tile.className = "source__tile";
      tile.setAttribute("data-source", source.key);
      tile.setAttribute(
        "aria-label",
        source.name + (connected ? ", connected" : ", not connected")
      );
      tile.appendChild(icon);
      tile.appendChild(name);
      tile.addEventListener("click", function () {
        openModal(source, tile);
      });

      var dot = document.createElement("span");
      dot.className = "source__dot";

      var status = document.createElement("p");
      status.className = "source__state";
      status.appendChild(dot);
      status.appendChild(
        document.createTextNode(connected ? "Connected" : "Not connected")
      );

      var cell = document.createElement("div");
      cell.className = "source";
      cell.setAttribute("data-state", connected ? "on" : "off");
      cell.appendChild(tile);
      cell.appendChild(status);
      el.sourcesGrid.appendChild(cell);
    });
    el.sourcesSubmit.disabled = !allConnected();
  }

  /* ------------------------------------------------- connection details */

  // The source the modal is currently collecting details for, and the tile
  // that opened it — focus goes back there on close.
  var modalSource = null;
  var modalOpener = null;

  function openModal(source, opener) {
    modalSource = source;
    modalOpener = opener || null;
    setMessage("modal", null, "");
    el.modalIcon.className = "lucide " + source.icon + " brand-icon";
    el.modalTitle.textContent = source.title;
    el.sourceAddress.value = (state.defaults && state.defaults[source.key]) || "";
    el.sourceUsername.value = "";
    restore(el.sourceUsername, source.userKey);
    el.sourcePassword.value = "";
    setBusy(el.modalSubmit, false, "Connecting", "Connect");
    el.modal.hidden = false;
    (el.sourceUsername.value ? el.sourcePassword : el.sourceUsername).focus();
  }

  function closeModal() {
    if (el.modal.hidden) {
      return;
    }
    el.modal.hidden = true;
    el.sourcePassword.value = "";
    modalSource = null;
    if (modalOpener && document.contains(modalOpener)) {
      modalOpener.focus();
    }
    modalOpener = null;
  }

  function wireModal() {
    clearOnInput(
      [el.sourceAddress, el.sourceUsername, el.sourcePassword],
      "modal"
    );

    Array.prototype.forEach.call(
      el.modal.querySelectorAll("[data-modal-close]"),
      function (node) {
        node.addEventListener("click", closeModal);
      }
    );

    document.addEventListener("keydown", function (event) {
      if (el.modal.hidden) {
        return;
      }
      if (event.key === "Escape") {
        closeModal();
      } else if (event.key === "Tab") {
        trapTab(event);
      }
    });

    el.modalForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitModal();
    });
  }

  // The modal is an overlay, not a <dialog>, so nothing stops Tab from
  // walking out into the card behind it — cycle it back round by hand.
  function trapTab(event) {
    var focusable = el.modal.querySelectorAll(
      "button:not(:disabled), input:not(:disabled)"
    );
    if (!focusable.length) {
      return;
    }
    var first = focusable[0];
    var last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function submitModal() {
    var source = modalSource;
    setMessage("modal", null, "");

    var credentials = {
      connection_address: el.sourceAddress.value,
      username: el.sourceUsername.value,
      password: el.sourcePassword.value
    };
    var blank = !credentials.connection_address
      ? el.sourceAddress
      : !credentials.username
      ? el.sourceUsername
      : !credentials.password
      ? el.sourcePassword
      : null;
    if (blank) {
      setMessage("modal", "error", "Address, username and password are required.");
      blank.focus();
      return;
    }

    setBusy(el.modalSubmit, true, "Connecting", "Connect");
    request("POST", source.endpoint, credentials)
      .then(function () {
        state.sources[source.key] = true;
        if (source.key === "config_mgmt_db") {
          // The server drops any saved selection when a new config-mgmt-DB
          // connection is opened, since it may point at a different database.
          state.selection = null;
          forgetContext();
        } else {
          // A new source repository may publish different versions, so what
          // the last one reported is no longer an answer about this one.
          candidateVersions = {};
        }
        remember(source.userKey, credentials.username);
        setBusy(el.modalSubmit, false, "Connecting", "Connect");
        closeModal();
        // The tile closeModal handed focus back to is about to be replaced,
        // so put focus on its stand-in — or on Continue, if that is now the
        // only thing left to do here.
        renderSources();
        renderStepper(state.view);
        var next = allConnected()
          ? el.sourcesSubmit
          : el.sourcesGrid.querySelector('[data-source="' + source.key + '"]');
        if (next) {
          next.focus();
        }
        setMessage("sources", "ok", source.name + " connected.");
      })
      .catch(function (error) {
        setBusy(el.modalSubmit, false, "Connecting", "Connect");
        if (!handleExpired(error)) {
          setMessage("modal", "error", error.message);
          el.sourcePassword.value = "";
          el.sourcePassword.focus();
        }
      });
  }

  function wireSources() {
    el.sourcesSubmit.addEventListener("click", function () {
      if (allConnected()) {
        enterSelect();
      }
    });
  }

  /* ------------------------------------------------------------- context */

  /* Fill the pickers, putting the saved selection back into them. Resolves
   * true when the pickers now hold it — which is what lets the cards past the
   * context step be entered, whether that is a reload deciding where to land
   * or the user stepping back here.
   *
   * A selection that no longer resolves is dropped on the server too: it
   * describes a context the database has stopped offering, and left in place
   * it would fail this same way on every reload. */
  function fillSelect() {
    var saved = state.selection;
    return loadProjects()
      .then(function () {
        if (!saved) {
          return false;
        }
        return restoreSelection(saved).then(function (complete) {
          if (complete) {
            return true;
          }
          state.selection = null;
          forgetContext();
          setMessage(
            "select",
            "error",
            "The saved context is no longer available. Pick it again."
          );
          return request("DELETE", API.selection)
            .catch(function () {
              // Saying so is what mattered; the server will offer it again.
            })
            .then(function () {
              return false;
            });
        });
      });
  }

  // Land on the right card after a refresh: where the user was standing, as
  // far as the selection behind it still resolves.
  function resumeContext() {
    return fillSelect()
      .then(function (complete) {
        if (!complete) {
          showView("select");
          return null;
        }
        return resumeCard();
      })
      .catch(function (error) {
        if (handleExpired(error)) {
          return;
        }
        showView("select");
        setMessage("select", "error", error.message);
      });
  }

  /* The card the session says the user was on, when the state behind it is
   * still there to show. The produced file the model card wants is looked up
   * in the listing rather than trusted from the record — it is a file on
   * disk, and another selection's run may have been cleaned up since. */
  function resumeCard() {
    var saved = state.ui || {};
    // Standing on one of the earlier cards with a context already confirmed
    // is a place to be, not a step left unfinished: the sources are there to
    // be reconnected and the pickers to be changed. Both are ready to use —
    // the sources card reads state the session carries, and the pickers were
    // just filled.
    if (saved.view === "sources") {
      return enterSources();
    }
    if (saved.view === "select") {
      return showView("select");
    }
    if (saved.view === "model" && saved.model_file) {
      return loadFiles().then(function () {
        state.modelFile = fileByRun(saved.model_file);
        if (state.modelFile) {
          return enterModel();
        }
        return resumeRunOrInventory();
      });
    }
    if (saved.view === "files") {
      return enterFiles();
    }
    return resumeRunOrInventory();
  }

  // A run still being tracked outranks the inventory: it is the thing that
  // was happening when the page went away.
  function resumeRunOrInventory() {
    return state.activeTask ? enterRunConsole() : enterInventory();
  }

  function fileByRun(runId) {
    var files = state.files || [];
    for (var i = 0; i < files.length; i++) {
      if (files[i].run_id === runId) {
        return files[i];
      }
    }
    return null;
  }

  /* Stepping back to the pickers. They are refilled from the database and the
   * saved selection put back into them, so this card reads the same however
   * it was reached — arriving from the sources card is not a reason to show
   * an empty context while the stepper still offers the cards past it. */
  function enterSelect() {
    return fillSelect()
      .then(function () {
        showView("select");
      })
      .catch(function (error) {
        if (handleExpired(error)) {
          return;
        }
        showView("select");
        setMessage("select", "error", error.message);
      });
  }

  function fill(select, items, valueKey, textKey, placeholder) {
    select.textContent = "";
    var blank = document.createElement("option");
    blank.value = "";
    blank.textContent = placeholder;
    select.appendChild(blank);
    items.forEach(function (item) {
      var option = document.createElement("option");
      option.value = item[valueKey];
      option.textContent = item[textKey];
      select.appendChild(option);
    });
    select.value = "";
  }

  function setPickerEnabled(picker, select, enabled) {
    select.disabled = !enabled;
    picker.classList.toggle("picker--disabled", !enabled);
  }

  function loadProjects() {
    setMessage("select", null, "");
    return request("GET", API.projects).then(function (payload) {
      fill(el.project, payload.projects, "project_id", "name", "Select project");
      clearPlatform();
      return payload.projects;
    });
  }

  function loadPlatforms(projectId) {
    return request(
      "GET",
      API.projects + "/" + encodeURIComponent(projectId) + "/platforms"
    ).then(function (payload) {
      fill(el.platform, payload.platforms, "platform_id", "name", "Select platform");
      setPickerEnabled(el.pickerPlatform, el.platform, true);
      return payload.platforms;
    });
  }

  function loadVersions(projectId, platformId) {
    return request(
      "GET",
      API.projects +
        "/" +
        encodeURIComponent(projectId) +
        "/platforms/" +
        encodeURIComponent(platformId) +
        "/versions"
    ).then(function (payload) {
      // Kept raw as well as mangled: the context strip wants the plain label
      // and the flag as a chip, not the "· current" the dropdown has to use.
      state.versions = payload.versions;
      var versions = payload.versions.map(function (version) {
        return {
          version_id: version.version_id,
          // The effective version is the one a run would normally target, so
          // say which it is rather than making the operator remember. The
          // CMDB calls it the current version, so the UI does too.
          label: version.is_effective
            ? version.label + "  ·  current"
            : version.label
        };
      });
      fill(el.version, versions, "version_id", "label", "Select version");
      setPickerEnabled(el.pickerVersion, el.version, true);
      return payload.versions;
    });
  }

  function clearPlatform() {
    fill(el.platform, [], "platform_id", "name", "Select platform");
    setPickerEnabled(el.pickerPlatform, el.platform, false);
    clearVersion();
  }

  function clearVersion() {
    fill(el.version, [], "version_id", "label", "Select version");
    setPickerEnabled(el.pickerVersion, el.version, false);
    syncSelectSubmit();
  }

  // Replay a saved selection through the cascade. Resolves false if any part
  // of it has disappeared from the database since it was saved.
  function restoreSelection(selection) {
    if (!hasOption(el.project, selection.project_id)) {
      return Promise.resolve(false);
    }
    el.project.value = selection.project_id;
    return loadPlatforms(selection.project_id)
      .then(function () {
        if (!hasOption(el.platform, selection.platform_id)) {
          return false;
        }
        el.platform.value = selection.platform_id;
        return loadVersions(selection.project_id, selection.platform_id).then(
          function () {
            if (!hasOption(el.version, selection.version_id)) {
              return false;
            }
            el.version.value = selection.version_id;
            return true;
          }
        );
      })
      .then(function (complete) {
        syncSelectSubmit();
        return complete;
      });
  }

  function hasOption(select, value) {
    for (var i = 0; i < select.options.length; i++) {
      if (select.options[i].value === value) {
        return true;
      }
    }
    return false;
  }

  function syncSelectSubmit() {
    el.selectSubmit.disabled = !(
      el.project.value &&
      el.platform.value &&
      el.version.value
    );
  }

  function selectedText(select) {
    var option = select.options[select.selectedIndex];
    return option ? option.textContent : "";
  }

  /* ----------------------------------------------------------- inventory */

  /* The Software Unit Version Inventory for the confirmed context (SRS
   * DSM-MSD req 10): the units that will run in that system version, with
   * the version of each. Derived from the configuration management database
   * on every visit rather than kept client-side, so it always reflects what
   * the database holds now. */
  // Every unit the database returned for this context. The filter narrows
  // what is drawn from here, so typing never costs a request.
  var allUnits = null;
  // Where the list was scrolled to when this card was last left. Stepping to
  // the produce card to look something up and coming back is one movement to
  // the user, so it should not cost them their place in the list.
  var unitScroll = 0;

  function enterInventory() {
    setMessage("inventory", null, "");
    renderContextLine();
    // The filter and the list already in hand are kept: what is re-read is
    // the inventory itself, which the card then swaps in underneath them.
    // Only a change of context clears them (they describe the one left
    // behind), and forgetInventory is what does that.
    renderUnits(allUnits);
    drawCandidateControl();
    showView("inventory");
    restoreInventoryScroll();
    return loadUnits()
      .then(function () {
        drawCandidateControl();
        restoreInventoryScroll();
      })
      .catch(function (error) {
        if (handleExpired(error)) {
          return;
        }
        renderUnits([]);
        drawCandidateControl();
        setMessage("inventory", "error", error.message);
      });
  }

  function keepInventoryScroll() {
    unitScroll = el.unitList.scrollTop;
  }

  function restoreInventoryScroll() {
    el.unitList.scrollTop = unitScroll;
  }

  // What the inventory card holds belongs to one context: a different one has
  // its own units, and a filter written against the old list means nothing
  // against the new.
  function forgetInventory() {
    allUnits = null;
    unitScroll = 0;
    el.unitFilter.value = "";
  }

  /* Everything held here that described one selection — the produced files
   * and the one on show, the candidate naming a unit of its inventory, and
   * the inventory card itself. Dropped together whenever the context changes
   * or goes away; the selection itself is the caller's to set, since it is
   * being replaced in some of those cases and cleared in others. */
  function forgetContext() {
    state.files = null;
    state.modelFile = null;
    state.model = null;
    state.candidate = null;
    forgetInventory();
  }

  function loadUnits() {
    var selection = state.selection;
    return request(
      "GET",
      API.projects +
        "/" +
        encodeURIComponent(selection.project_id) +
        "/platforms/" +
        encodeURIComponent(selection.platform_id) +
        "/versions/" +
        encodeURIComponent(selection.version_id) +
        "/units"
    ).then(function (payload) {
      renderUnits(payload.units);
      return payload.units;
    });
  }

  // The confirmed context, as a labelled strip above the list it scopes —
  // the pickers hold the labels, which read better than the raw ids the
  // selection carries.
  function renderContextLine() {
    var version = selectedVersion();
    el.contextProject.textContent = selectedText(el.project);
    el.contextPlatform.textContent = selectedText(el.platform);
    el.contextVersion.textContent = version
      ? version.label
      : selectedText(el.version);
    el.contextCurrent.hidden = !(version && version.is_effective);
  }

  function selectedVersion() {
    var id = el.version.value;
    var versions = state.versions || [];
    for (var i = 0; i < versions.length; i++) {
      if (versions[i].version_id === id) {
        return versions[i];
      }
    }
    return null;
  }


  // units: null while the request is in flight, [] for a version that has
  // none recorded, otherwise the rows.
  function renderUnits(units) {
    allUnits = units;
    paintUnits();
  }

  function paintUnits() {
    drawUnits();
    lockListHeight();
  }

  /* Filtering must not resize the box. The height the full list settles at —
   * its own height, or the CSS cap once it overflows — is held as a floor, so
   * rows disappearing under a filter never make the card jump. Only the
   * unfiltered list is measured; a narrowed one inherits that floor. */
  function lockListHeight() {
    if (el.unitFilter.value) {
      return;
    }
    el.unitList.style.minHeight = "";
    // Never above the stylesheet's own cap, which is viewport-relative: a
    // floor measured on a tall window would otherwise hold the list at that
    // height on a short one — min-height beats max-height — and push the
    // card past the fold, which is the very thing the cap is there to stop.
    var height = Math.min(el.unitList.offsetHeight, listHeightCap());
    if (height) {
      el.unitList.style.minHeight = height + "px";
    }
  }

  function listHeightCap() {
    var cap = parseFloat(window.getComputedStyle(el.unitList).maxHeight);
    return isNaN(cap) ? Infinity : cap;
  }

  function drawUnits() {
    el.unitList.textContent = "";

    if (allUnits === null) {
      el.unitCount.textContent = "";
      el.unitFilter.disabled = true;
      var spinner = document.createElement("span");
      spinner.className = "spinner";
      var loading = document.createElement("p");
      loading.className = "units__empty";
      loading.appendChild(spinner);
      loading.appendChild(document.createTextNode("Reading inventory"));
      el.unitList.appendChild(loading);
      return;
    }

    el.unitFilter.disabled = !allUnits.length;

    var query = el.unitFilter.value.trim().toLowerCase();
    var shown = query
      ? allUnits.filter(function (unit) {
          return unit.unit_name.toLowerCase().indexOf(query) !== -1;
        })
      : allUnits;

    // The total stays visible while filtering, so a narrow result never
    // reads as a short inventory.
    el.unitCount.textContent = !allUnits.length
      ? ""
      : query
      ? shown.length + " / " + allUnits.length
      : String(allUnits.length);

    if (!allUnits.length) {
      var empty = document.createElement("p");
      empty.className = "units__empty";
      empty.textContent = "No software units recorded for this version.";
      el.unitList.appendChild(empty);
      return;
    }

    if (!shown.length) {
      var noMatch = document.createElement("p");
      noMatch.className = "units__empty";
      noMatch.textContent = "No unit matches that filter.";
      el.unitList.appendChild(noMatch);
      return;
    }

    shown.forEach(function (unit) {
      // The candidate is overlaid at draw time rather than written into the
      // rows: allUnits stays the database's own answer, so clearing the
      // candidate restores the pinned version without another request.
      var candidate = candidateFor(unit.unit_name);

      var name = document.createElement("span");
      name.className = "units__name";
      name.textContent = unit.unit_name;

      var version = document.createElement("span");
      version.className = "units__version";
      version.textContent = candidate ? candidate.version : unit.version;

      var row = document.createElement("div");
      row.className = "units__row";
      row.appendChild(name);
      // A candidate version is the one being evaluated for installation
      // rather than the one the system version pins (req 11).
      if (candidate || unit.is_candidate) {
        var badge = document.createElement("span");
        badge.className = "units__badge";
        badge.textContent = "Candidate";
        row.appendChild(badge);
      }
      row.appendChild(version);
      el.unitList.appendChild(row);
    });
  }

  function candidateFor(unitName) {
    return state.candidate && state.candidate.unit_name === unitName
      ? state.candidate
      : null;
  }

  /* ------------------------------------------------------- candidate */

  /* The software unit version being evaluated for installation into the
   * target environment (SRS DSM-MSD req 11). One unit at a time: the run
   * acquires that version for that unit and the versions this system version
   * defines for every other, so naming a second would describe a system
   * nobody is proposing.
   *
   * The versions on offer come from the unit's source repository, not the
   * configuration management database — a candidate is by definition a
   * version no system version defines yet. */

  // Versions per unit as the repository last reported them, so stepping back
  // through the units already looked at costs nothing.
  var candidateVersions = {};

  function baselineVersion(unitName) {
    var row = unitRow(unitName);
    return row ? row.version : null;
  }

  function unitRow(unitName) {
    var units = allUnits || [];
    for (var i = 0; i < units.length; i++) {
      if (units[i].unit_name === unitName) {
        return units[i];
      }
    }
    return null;
  }

  function drawCandidateControl() {
    var units = allUnits || [];
    // A candidate names a unit of this inventory; if the selection changed
    // under it, it no longer describes anything. Only once the inventory has
    // arrived, though — while it is in flight there is nothing to check
    // against, and a candidate restored from a run in flight would be lost.
    if (allUnits && state.candidate && !unitRow(state.candidate.unit_name)) {
      state.candidate = null;
    }

    el.candidateUnit.textContent = "";
    // The same dash the version picker shows when unset, so with no unit
    // chosen the line reads as one unset pair rather than as a sentence
    // about evaluating nothing.
    el.candidateUnit.appendChild(option("", "—"));
    units.forEach(function (unit) {
      el.candidateUnit.appendChild(option(unit.unit_name, unit.unit_name));
    });
    el.candidateUnit.disabled = !units.length;
    el.candidateUnit.value = state.candidate ? state.candidate.unit_name : "";

    if (!el.candidateUnit.value) {
      clearVersionPicker();
      return;
    }
    fillVersionPicker(el.candidateUnit.value);
  }

  function option(value, label) {
    var node = document.createElement("option");
    node.value = value;
    node.textContent = label;
    return node;
  }

  function clearVersionPicker() {
    el.candidateVersion.textContent = "";
    // A dash rather than nothing: an empty select is a blank box that reads
    // as broken, where a dash reads as "not yet".
    el.candidateVersion.appendChild(option("", "—"));
    setPickerEnabled(el.candidateVersionPicker, el.candidateVersion, false);
    setCandidateNote("");
  }

  function setCandidateNote(text, isError) {
    el.candidateNote.textContent = text;
    el.candidateNote.classList.toggle("candidate__note--error", !!isError);
  }

  // Offers the version this system version defines alongside the others the
  // repository publishes, so choosing the candidate and taking it back are
  // the same control rather than two.
  function fillVersionPicker(unitName) {
    var known = candidateVersions[unitName];
    if (known) {
      paintVersionPicker(unitName, known);
      return Promise.resolve(known);
    }
    el.candidateVersion.textContent = "";
    setPickerEnabled(el.candidateVersionPicker, el.candidateVersion, false);
    setCandidateNote("Reading published versions…");
    return request("GET", unitVersionsUrl(unitName))
      .then(function (payload) {
        candidateVersions[unitName] = payload.versions || [];
        // The user may have moved on while this was in flight.
        if (el.candidateUnit.value === unitName) {
          paintVersionPicker(unitName, candidateVersions[unitName]);
        }
        return candidateVersions[unitName];
      })
      .catch(function (error) {
        if (handleExpired(error)) {
          return [];
        }
        if (el.candidateUnit.value === unitName) {
          setCandidateNote(error.message, true);
        }
        return [];
      });
  }

  function paintVersionPicker(unitName, versions) {
    var baseline = baselineVersion(unitName);
    var candidate = candidateFor(unitName);

    el.candidateVersion.textContent = "";
    // The version already in the inventory, marked for what choosing it
    // does: it is how a candidate is taken back, not a candidate itself.
    el.candidateVersion.appendChild(option(baseline, baseline + " · no change"));
    versions.forEach(function (version) {
      if (version !== baseline) {
        el.candidateVersion.appendChild(option(version, version));
      }
    });
    // A candidate the repository no longer publishes still belongs in the
    // list — it is what the user chose, and dropping it silently would
    // change their run without saying so.
    if (candidate && !hasCandidateVersion(candidate.version)) {
      el.candidateVersion.appendChild(option(candidate.version, candidate.version));
    }

    el.candidateVersion.value = candidate ? candidate.version : baseline;
    setPickerEnabled(el.candidateVersionPicker, el.candidateVersion, true);
    setCandidateNote(
      versions.length
        ? ""
        : "The source repository publishes no versions for " + unitName + "."
    );
  }

  function hasCandidateVersion(value) {
    return hasOption(el.candidateVersion, value);
  }

  function onCandidateUnitChange() {
    var unitName = el.candidateUnit.value;
    // Switching units drops the candidate: it named the unit that was there.
    if (!state.candidate || state.candidate.unit_name !== unitName) {
      state.candidate = null;
      paintUnits();
      // The candidate is the one thing chosen on this card that a reload has
      // to come back to, and it changes without a change of card.
      rememberUi();
    }
    if (!unitName) {
      clearVersionPicker();
      return;
    }
    fillVersionPicker(unitName);
  }

  function onCandidateVersionChange() {
    var unitName = el.candidateUnit.value;
    var version = el.candidateVersion.value;
    // Choosing back the version this system version defines is how a
    // candidate is taken back — it is not a candidate, it is the baseline.
    state.candidate =
      unitName && version && version !== baselineVersion(unitName)
        ? { unit_name: unitName, version: version }
        : null;
    paintUnits();
    rememberUi();
  }

  /* ----------------------------------------------------------------- run */

  /* Model Setup Data production for the confirmed context (SRS DSM-VAE req
   * 6, 8): submit the run, then follow the worker's own log output and task
   * state over one SSE stream until a terminal `status` arrives. The stream
   * carries the lines, a `status` event on every state change (with a
   * snapshot on every connect), a `ping` while the run is quiet, and the
   * terminal `status` — so there is no polling, and re-dialing (with the
   * last line id) resumes the lines it already delivered rather than
   * replaying them. The client closes the stream on the terminal state; the
   * server's own close after that is only a leak guard. */
  var runSource = null;
  var runState = null;
  /* A run goes quiet for minutes at a time, and a connection that carries
   * nothing for that long can be dropped somewhere on the path without a
   * FIN — leaving EventSource holding a socket it still believes in, so it
   * never reconnects on its own and the card sits on a state the run left
   * long ago. The server's `ping` is what makes that detectable: nothing at
   * all for STREAM_STALE_MS means the stream is gone whatever the browser
   * thinks, and the answer is to open a new one from the last line seen. */
  var STREAM_STALE_MS = 60000;
  var STREAM_WATCH_MS = 10000;
  var runStreamTaskId = null;
  var runStreamAt = 0;
  var runStreamWatch = null;
  var runStreamRetrying = false;
  /* Re-dial bookkeeping: how many consecutive re-opens came up with no event
   * at all (a dead API, an expired session), the pending re-dial, and the
   * point at which re-dialing is stopped in favour of telling the operator. */
  var STREAM_REDIAL_MS = 1000;
  var STREAM_REDIAL_MAX_FAILS = 5;
  var runStreamFails = 0;
  var runStreamRetryTimer = null;
  var runStreamGivenUp = false;
  /* Where a reopened stream resumes from. Kept in step with what the console
   * is actually showing — resetConsole() clears it, so a console starting
   * empty is refilled from the top. */
  var runStreamLastId = null;

  /* The Produce stage opens on what has already been produced, not on the
   * console: making another Model Setup Data file is a choice taken after
   * seeing what exists, not the only thing this stage offers. A run already
   * in flight outranks that — it is the thing that was happening. */
  function enterProduce() {
    // Only a run still going outranks the list — once it has ended, its file
    // is in the list like any other, and the list is what this stage is for.
    var live = !!state.activeTask && !RUN_TERMINAL[runState];
    return live ? enterRunConsole() : enterFiles();
  }

  function enterFiles() {
    /* Reachable while a run is going, by stepping back off the console. This
     * session tracks one run at a time, so starting a second here would
     * orphan the first — the card says so rather than silently doing it.
     *
     * A reload can land here holding a tracked run this page has never
     * attached to, and how that run ended is only on its stream: until it is
     * opened the run is neither known to be going nor known to be over. So
     * the card says which of the two it is telling the user, and the way to
     * settle it is the button beside Produce. */
    var tracked = !!state.activeTask;
    var live = tracked && runState !== null && !RUN_TERMINAL[runState];
    var unattached = tracked && runState === null;
    el.filesProduce.disabled = live || unattached;
    // The way back into the run this session is tracking, going or finished.
    // A finished one is not on offer anywhere else: its file is in the list
    // like any other, but the log of how it was produced is only here.
    el.filesLog.hidden = !tracked;
    setMessage(
      "files",
      null,
      live
        ? "A production run is already in progress."
        : unattached
        ? "This session is tracking a production run. Open its log to see where it got to."
        : ""
    );
    showView("files");
    loadFiles();
  }

  function enterRunConsole() {
    setMessage("run", null, "");
    var task = state.activeTask;
    resetConsole();
    if (!task) {
      setRunState(null, null);
      showView("run");
      return;
    }
    // Re-attaching: the stream replays this run's lines from the store, so
    // the console fills itself in.
    setRunState("PENDING", null);
    showView("run");
    openRunStream(task.task_id);
  }

  /* What has already been produced for this context, before anyone spends a
   * run reproducing it (SRS DSM-VAE req 5). Scoped by project/platform/version
   * rather than by user: a Model Setup Data file belongs to the selection it
   * describes, so the list shows everyone's, and each row says who produced
   * it. Read fresh on every visit — another user may have produced one since. */
  function loadFiles() {
    var selection = state.selection;
    if (!selection) {
      return Promise.resolve();
    }
    renderFiles(state.files);
    return request("GET", msdFilesUrl(selection))
      .then(function (payload) {
        // The selection changed while this was in flight.
        if (state.selection !== selection) {
          return;
        }
        state.files = payload.files || [];
        renderFiles(state.files);
      })
      .catch(function (error) {
        if (!handleExpired(error)) {
          // The list is unknown, not empty — but the card has to show
          // something, so it shows nothing plus the reason why.
          state.files = [];
          renderFiles([]);
          setMessage("files", "error", error.message);
        }
      });
  }

  function renderFiles(files) {
    el.runFiles.textContent = "";
    // Null means "not asked yet" — say nothing rather than claiming there are
    // none, which would be wrong for the moment before the list arrives.
    el.runFilesPanel.hidden = files === null;
    if (files === null) {
      return;
    }
    el.runFilesEmpty.hidden = files.length > 0;
    files.forEach(function (file) {
      el.runFiles.appendChild(fileRow(file));
    });
  }

  function fileRow(file) {
    var row = document.createElement("li");
    row.className = "filerow";

    var main = document.createElement("div");
    main.className = "filerow__main";

    var when = document.createElement("span");
    when.className = "filerow__when";
    when.textContent = generatedAt(file.generated_at);
    main.appendChild(when);

    var by = document.createElement("span");
    by.className = "filerow__by";
    by.textContent = file.produced_by || "unknown";
    main.appendChild(by);

    var scale = document.createElement("span");
    scale.className = "filerow__scale";
    scale.textContent = scaleSummary(file.scale);
    main.appendChild(scale);

    // Several files for one selection can differ only by the candidate they
    // were produced with (SRS DSM-MSD req 11), so the one that carried one
    // says which — the rest read as the versions the system version defines.
    if (file.candidate) {
      var candidate = document.createElement("span");
      candidate.className = "units__badge";
      candidate.textContent =
        file.candidate.unit_name + " " + file.candidate.version;
      main.appendChild(candidate);
    }

    row.appendChild(main);

    var actions = document.createElement("div");
    actions.className = "filerow__actions";

    var open = document.createElement("button");
    open.type = "button";
    open.className = "submit submit--ghost submit--compact";
    open.innerHTML = '<span class="submit__label">Open</span>';
    open.addEventListener("click", function () {
      openFile(file);
    });
    actions.appendChild(open);

    var download = document.createElement("a");
    download.className = "submit submit--ghost submit--compact";
    download.href = msdFilesUrl(state.selection, file.run_id, "download");
    download.setAttribute("download", "");
    download.innerHTML =
      '<i class="lucide lucide-download"></i>' +
      '<span class="submit__label">Download</span>';
    actions.appendChild(download);

    row.appendChild(actions);
    return row;
  }

  // A produced file the user picked: it becomes what the Model card shows,
  // exactly as a run that just finished would (SRS DSM-VAE req 5 — select the
  // file to be used).
  function openFile(file) {
    if (state.modelFile && state.modelFile.run_id === file.run_id) {
      enterModel();
      return;
    }
    state.modelFile = file;
    state.model = null;
    enterModel();
  }

  // The same four counts the Model card's scale cells show, in the same
  // order, so a row previews what opening it leads to.
  function scaleSummary(scale) {
    var parts = [];
    SCALE_CELLS.forEach(function (cell) {
      if (scale && scale[cell.key] !== undefined) {
        parts.push(scale[cell.key] + " " + cell.label.toLowerCase());
      }
    });
    return parts.join(" · ");
  }

  function wireRun() {
    // Producing another is a decision taken on the files card; the console is
    // where it is then watched. So this is the one control that crosses from
    // one card to the other, and it submits rather than offering to submit —
    // the choice was already made by pressing it.
    el.filesProduce.addEventListener("click", function () {
      // Not enterRunConsole(): that re-attaches to whatever run this session
      // last tracked, and the point here is a new one. The console opens
      // empty and already reading as queued, so the wait for the submit to
      // come back does not look like an idle card.
      closeRunStream();
      resetConsole();
      setRunState("PENDING", null);
      showView("run");
      startRun();
    });
    // Back into the tracked run, replaying its lines from the store — the
    // same thing a reload does, so stepping away costs nothing.
    el.filesLog.addEventListener("click", enterRunConsole);
    el.runBack.addEventListener("click", enterFiles);
    // Start survives on the console only as a retry after a run that failed
    // or was cancelled — the first submit comes from the files card.
    el.runStart.addEventListener("click", startRun);
    el.runModel.addEventListener("click", enterModel);

    el.runCancel.addEventListener("click", function () {
      var task = state.activeTask;
      if (!task) {
        return;
      }
      setBusy(el.runCancel, true, "Cancelling", "Cancel");
      request("POST", taskUrl(task.task_id, "cancel"))
        .then(function () {
          // The revocation lands as a status event on the open stream; the
          // button stays busy until it does.
        })
        .catch(function (error) {
          setBusy(el.runCancel, false, "Cancelling", "Cancel");
          if (!handleExpired(error)) {
            setMessage("run", "error", error.message);
          }
        });
    });
  }

  function startRun() {
    setMessage("run", null, "");
    resetConsole();
    setBusy(el.runStart, true, "Submitting", "Start production");
    var body = {
      project_id: state.selection.project_id,
      platform_id: state.selection.platform_id,
      version_id: state.selection.version_id
    };
    // Sent only when one was chosen: a run with no candidate is a run of the
    // versions this system version defines (SRS DSM-MSD req 11).
    if (state.candidate) {
      body.candidate = state.candidate;
    }
    request("POST", API.run, body)
      .then(function (payload) {
        state.activeTask = {
          task_id: payload.task_id,
          project_id: state.selection.project_id,
          platform_id: state.selection.platform_id,
          version_id: state.selection.version_id,
          candidate: state.candidate
        };
        setBusy(el.runStart, false, "Submitting", "Start production");
        setRunState("PENDING", null);
        openRunStream(payload.task_id);
      })
      .catch(function (error) {
        setBusy(el.runStart, false, "Submitting", "Start production");
        setRunState(null, null);
        if (!handleExpired(error)) {
          setMessage("run", "error", error.message);
        }
      });
  }

  function openRunStream(taskId) {
    // A user-initiated open must not race a pending re-dial, and a new run
    // starts with a clean re-dial slate.
    if (runStreamRetryTimer) {
      window.clearTimeout(runStreamRetryTimer);
      runStreamRetryTimer = null;
    }
    if (taskId !== runStreamTaskId) {
      runStreamFails = 0;
      runStreamGivenUp = false;
    }
    closeRunStream();
    if (!window.EventSource) {
      setMessage(
        "run",
        "error",
        "This browser cannot follow the run. Reload to see the result."
      );
      return;
    }
    runStreamTaskId = taskId;
    /* A stream this code opens is a new one, and would replay the whole run
     * into a console that already holds it — so where to resume from is said
     * in the URL, and the id of the last line seen survives the reopen. */
    var url = taskUrl(taskId, "output");
    if (runStreamLastId !== null) {
      url += "?last_event_id=" + encodeURIComponent(runStreamLastId);
    }
    runSource = new EventSource(url);
    // Arm the watchdog against this opening, not the last one. Not
    // markRunStream(): an event, not a dial, is what proves the stream alive —
    // resetting the re-dial slate here would defeat the give-up count while
    // the API is down.
    runStreamAt = Date.now();
    runSource.onmessage = function (event) {
      markRunStream(event);
      appendConsole(event.data);
    };
    // Nothing to draw: a ping only says the stream is still there, which is
    // the whole point of it.
    runSource.addEventListener("ping", markRunStream);
    runSource.addEventListener("status", handleRunStatus);
    /* Closing the source on the re-dial also suppresses EventSource's own
     * retry: the app is the only thing re-dialing, and it counts its
     * failures. */
    runSource.onerror = function () {
      if (RUN_TERMINAL[runState]) {
        closeRunStream();
        return;
      }
      runStreamFails += 1;
      if (runStreamFails >= STREAM_REDIAL_MAX_FAILS) {
        runStreamGivenUp = true;
        runStreamRetrying = false;
        closeRunStream();
        setMessage(
          "run",
          "error",
          "Lost the connection to the run. Reload the page to continue."
        );
        return;
      }
      runStreamRetrying = true;
      setMessage("run", "info", "Reconnecting to the run…");
      runStreamRetryTimer = window.setTimeout(function () {
        runStreamRetryTimer = null;
        openRunStream(runStreamTaskId);
      }, STREAM_REDIAL_MS);
    };
    /* The watchdog catches the drops the browser never notices (no FIN):
     * silence for STREAM_STALE_MS is a dead stream whatever the socket
     * believes. It shares the re-dial path, and stands down once re-dialing
     * has been given up. */
    runStreamWatch = window.setInterval(function () {
      if (
        runStreamGivenUp ||
        !runStreamTaskId ||
        Date.now() - runStreamAt < STREAM_STALE_MS
      ) {
        return;
      }
      openRunStream(runStreamTaskId);
    }, STREAM_WATCH_MS);
  }

  // Any event at all is proof the stream is alive: it arms the watchdog,
  // resets the re-dial slate, and takes down a reconnection notice the
  // operator no longer needs to see.
  function markRunStream(event) {
    runStreamAt = Date.now();
    if (event && event.lastEventId) {
      runStreamLastId = event.lastEventId;
    }
    runStreamFails = 0;
    runStreamGivenUp = false;
    if (runStreamRetrying) {
      runStreamRetrying = false;
      setMessage("run", null, "");
    }
  }

  function closeRunStream() {
    if (runStreamRetryTimer) {
      window.clearTimeout(runStreamRetryTimer);
      runStreamRetryTimer = null;
    }
    if (runStreamWatch) {
      window.clearInterval(runStreamWatch);
      runStreamWatch = null;
    }
    if (runSource) {
      runSource.close();
      runSource = null;
    }
  }

  function handleRunStatus(event) {
    markRunStream(event);
    var status;
    try {
      status = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    setRunState(status.state, status);
    /* A terminal status is the terminator: closing here is what ends the
     * stream. The server's grace close afterwards is only a leak guard for a
     * client that vanished. */
    if (RUN_TERMINAL[status.state]) {
      closeRunStream();
    }
  }

  // status is the payload for a finished run, or null when there is nothing
  // to report yet.
  function setRunState(taskState, status) {
    runState = taskState;
    var known = RUN_STATES[taskState] || null;
    var running = !!taskState && !RUN_TERMINAL[taskState];

    el.runStatus.setAttribute("data-tone", known ? known.tone : "idle");
    el.runStatusValue.textContent = known ? known.label : "Not started";

    // The panel flashes once on the way into a terminal state. Dropping the
    // class and reading layout back restarts the animation, so a second run
    // ending the same way flashes again rather than sitting on a class it
    // already carries.
    el.runStatus.classList.remove("runpanel--flash");
    if (RUN_TERMINAL[taskState]) {
      void el.runStatus.offsetWidth;
      el.runStatus.classList.add("runpanel--flash");
    }

    /* A run that wrote a file makes that file the one the model stage shows,
     * the same way picking one from the list above does — a reload re-earns
     * the stage this way too, since re-attaching replays the terminal status
     * through here. Re-attaching to the run whose file is already showing
     * must not drop it, so the pointer only moves when a *different* run has
     * something to say: a newer run starting invalidates whatever is showing
     * (the file itself stays listed, one click away), the same run reporting
     * again does not. */
    var runId = status && status.result && status.result.run_id;
    var ready = taskState === "SUCCESS" && !!runId;
    var task = state.activeTask ? state.activeTask.task_id : null;

    /* Start is the row's one action until a run produces something; once it
     * has, Core System Model takes that place rather than sitting beside a
     * second offer to redo work that already succeeded. A run that failed or
     * was cancelled leaves Start where it was, so retrying stays one click. */
    el.runStart.hidden = running || ready;
    setBusy(el.runStart, false, "Submitting", "Start production");
    el.runCancel.hidden = !running;
    setBusy(el.runCancel, false, "Cancelling", "Cancel");

    el.runModel.hidden = !ready;
    var shownRun = state.modelFile ? state.modelFile.run_id : null;
    if (ready ? shownRun !== runId : shownRun && shownRun !== task) {
      state.modelFile = ready
        ? {
            run_id: runId,
            produced_by: state.username,
            generated_at: null,
            scale: status.result.scale
          }
        : null;
      state.model = null;
      // The run ends while this card is already on screen, so the stage it
      // just unlocked has to be redrawn — and the file it just made recorded —
      // rather than waiting for a view change.
      renderStepper(state.view);
      rememberUi();
    }
    if (ready) {
      // The run just added a file to this selection's list, and the card
      // showing that list is the one on screen.
      loadFiles();
    }

    renderRunSummary(status);

    if (status && status.error) {
      setMessage("run", "error", status.error);
    } else if (taskState === "SUCCESS") {
      setMessage("run", "ok", "Model Setup Data produced.");
    }
  }

  // Per-unit outcomes of a finished run, as one chip per status that
  // actually occurred — an all-ok run says so in a single chip.
  function renderRunSummary(status) {
    el.runSummary.textContent = "";
    var units = (status && status.result && status.result.units) || [];
    if (!units.length) {
      el.runSummary.hidden = true;
      return;
    }
    var counts = {};
    var order = [];
    units.forEach(function (unit) {
      if (counts[unit.status] === undefined) {
        counts[unit.status] = 0;
        order.push(unit.status);
      }
      counts[unit.status] += 1;
    });
    order.forEach(function (key) {
      var chip = document.createElement("span");
      chip.className = "chip";
      chip.setAttribute("data-status", key);
      chip.textContent = counts[key] + " " + key.replace(/_/g, " ");
      el.runSummary.appendChild(chip);
    });
    el.runSummary.hidden = false;
  }

  // The worker formats every line as "%(asctime)s %(levelname)-8s
  // %(message)s" with an %H:%M:%S clock (worker.py), so the three parts can
  // be told apart and styled. Anything that does not match — a traceback's
  // continuation lines, most of all — is rendered whole.
  // The level's own padding is captured rather than rebuilt, so the columns
  // line up exactly as the formatter wrote them.
  var LOG_LINE =
    /^(\d{2}:\d{2}:\d{2})\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)(\s+)([\s\S]*)$/;

  function resetConsole() {
    // The console and the resume point are one thing: emptying it means the
    // next stream has to start from the run's first line again.
    runStreamLastId = null;
    el.console.textContent = "";
    var idle = document.createElement("p");
    idle.className = "console__idle";
    var icon = document.createElement("i");
    icon.className = "lucide lucide-rocket";
    idle.appendChild(icon);
    idle.appendChild(document.createTextNode("Awaiting launch"));
    el.console.appendChild(idle);
    el.console.classList.add("console--empty");
    el.console.hidden = false;
  }

  function appendConsole(line) {
    // The first line replaces the standing-by note, and the console stops
    // centring what it holds.
    if (el.console.classList.contains("console--empty")) {
      el.console.textContent = "";
      el.console.classList.remove("console--empty");
    }

    var atBottom =
      el.console.scrollTop + el.console.clientHeight >=
      el.console.scrollHeight - 4;
    var row = document.createElement("div");
    row.className = "console__line";

    var parts = LOG_LINE.exec(line);
    if (parts) {
      row.setAttribute("data-level", parts[2]);
      row.appendChild(consolePart("console__time", parts[1] + " "));
      var level = consolePart("console__level", parts[2]);
      level.setAttribute("data-level", parts[2]);
      row.appendChild(level);
      row.appendChild(consolePart("console__text", parts[3] + parts[4]));
    } else {
      row.textContent = line;
    }

    el.console.appendChild(row);
    // Follow the tail only while the operator is already at it — scrolling
    // back to read something must not be yanked away by the next line.
    if (atBottom) {
      el.console.scrollTop = el.console.scrollHeight;
    }
  }

  // textContent throughout: these lines are the worker's own output, so
  // nothing in them is ever parsed as markup.
  function consolePart(className, text) {
    var span = document.createElement("span");
    span.className = className;
    span.textContent = text;
    return span;
  }

  /* --------------------------------------------------------------- model */

  /* The Model Setup Data file itself, read back a panel at a time (SRS
   * DSM-VAE req 8): the context it was generated for, its scale, the topics
   * with their QoS, the applications with their placement in the system, the
   * graph's own edges, and the acquisition log behind all of it. Everything
   * shown is a field of the file — nothing is computed from it beyond
   * counting rows and resolving an id to the name it stands for.
   *
   * The file is fetched once per run and kept, so stepping between Produce
   * and Model does not ask the server for it again. */

  // What the writer leaves wherever a source had nothing to give.
  var MISSING = "NOT_FOUND";

  function enterModel() {
    setMessage("model", null, "");
    if (!state.modelFile) {
      // No file picked and none produced; the files card is where one is
      // chosen or a run is started to make one.
      enterFiles();
      return;
    }
    var file = state.modelFile;
    var runId = file.run_id;
    el.modelDownload.href = msdFilesUrl(state.selection, runId, "download");
    showView("model");

    if (state.model) {
      renderModel(state.model);
      return;
    }
    el.modelContext.hidden = true;
    el.modelGrid.hidden = true;
    el.modelLoading.hidden = false;
    request("GET", msdFilesUrl(state.selection, runId, "model"))
      .then(function (model) {
        el.modelLoading.hidden = true;
        // A newer run finished, or another file was picked, while this read
        // was in flight; that one owns the card now.
        if (!state.modelFile || state.modelFile.run_id !== runId) {
          return;
        }
        state.model = model;
        renderModel(model);
      })
      .catch(function (error) {
        el.modelLoading.hidden = true;
        if (!handleExpired(error)) {
          setMessage("model", "error", error.message);
        }
      });
  }

  function renderModel(model) {
    renderModelContext(model);
    renderModelScale(model);
    renderModelInventory((model.inventory || {}).units || []);
    renderModelLog(model);
    renderModelErrors(model);

    el.modelGrid.hidden = false;
  }

  function renderModelContext(model) {
    var context = model.context || {};
    var version = context.version || {};
    el.modelProject.textContent = shown((context.project || {}).name);
    el.modelPlatform.textContent = shown((context.platform || {}).name);
    el.modelVersion.textContent = shown(version.label);
    el.modelCurrent.hidden = !version.is_effective;
    el.modelGenerated.textContent = generatedAt(model.generated_at);
    el.modelContext.hidden = false;
  }

  /* The counts the file's own metadata carries — not the lengths of the
   * lists behind them, which is exactly what makes them worth showing. */
  var SCALE_CELLS = [
    { key: "apps", label: "Applications" },
    { key: "topics", label: "Topics" },
    { key: "nodes", label: "Nodes" },
    { key: "libraries", label: "Libraries" }
  ];

  function renderModelScale(model) {
    var scale = ((model.graph || {}).metadata || {}).scale || {};
    el.modelScale.textContent = "";
    SCALE_CELLS.forEach(function (cell) {
      var box = document.createElement("div");
      box.className = "scale__cell";
      var count = scale[cell.key];
      box.appendChild(
        span("scale__value", count === undefined ? "—" : String(count))
      );
      box.appendChild(span("scale__label", cell.label));
      el.modelScale.appendChild(box);
    });
  }

  // Every software unit version the inventory holds for this context, not
  // only the ones a run went on to acquire.
  function renderModelInventory(units) {
    setPanelCount(el.modelUnitCount, units.length);
    if (!units.length) {
      emptyPanel(el.modelUnits, "No software units in this inventory.");
      return;
    }
    el.modelUnits.textContent = "";
    units.forEach(function (unit) {
      var built = modelRow(el.modelUnits);
      built.head.appendChild(span("mrow__name", shown(unit.unit_name)));
      if (unit.is_candidate) {
        built.head.appendChild(span("units__badge", "Candidate"));
      }
      built.head.appendChild(span("mrow__value", shown(unit.version)));
    });
  }

  /* What was read to build the model: one row per file the run went for,
   * with the status it came back with, under a heading for the unit it was
   * read from. What went wrong is next door.
   *
   * The generator walks the inventory unit by unit, so the records already
   * arrive in runs that share a unit and a version. Heading a run says the
   * pair once where a line under every file said it once per row — and the
   * rows themselves then have the width to be read. Nothing is reordered
   * here: a run ends where the file's own order ends it. */
  function renderModelLog(model) {
    var files = model.acquired_files || [];
    setPanelCount(el.modelLogCount, files.length);
    if (!files.length) {
      emptyPanel(el.modelLog, "Nothing was acquired for this model.");
      return;
    }
    el.modelLog.textContent = "";
    var group = null;
    var heading = null;
    files.forEach(function (file) {
      // A run acquires one version of a unit, so either half of the pair
      // changing is a new unit as far as the log is concerned.
      var key = shown(file.unit_name) + " " + shown(file.package_version);
      if (key !== heading) {
        heading = key;
        group = logGroup(file);
      }
      logRow(group, file);
    });
  }

  function logGroup(file) {
    var group = document.createElement("div");
    group.className = "mgroup";
    var head = document.createElement("div");
    head.className = "mgroup__head";
    head.appendChild(span("mgroup__name", shown(file.unit_name)));
    head.appendChild(span("mgroup__version", shown(file.package_version)));
    group.appendChild(head);
    el.modelLog.appendChild(group);
    return group;
  }

  function logRow(group, file) {
    var built = modelRow(group);
    // Colour alone is not a status: the dot names itself on hover, and a file
    // that did not come through says so in words beside it. A row that did is
    // left to the dot — every row carrying an OK chip made the exceptions
    // harder to find, not easier.
    built.head.appendChild(dot(file.status, words(file.status)));
    var name = span("mrow__name", shown(file.file_name));
    // Where it was read from. Held back to the tooltip because the writer
    // records an absolute path on the worker's disk, which is longer than the
    // row and means nothing on the reader's machine.
    name.title = file.file_path || shown(file.file_name);
    built.head.appendChild(name);
    if (String(file.status).toUpperCase() !== "OK") {
      built.head.appendChild(chip(words(file.status), file.status));
    }
    // A file that could not be read says why under itself: what went wrong
    // reaching it belongs to the file, not to the validation the panel next
    // door reports. All of a row's reasons go into one grid rather than a
    // box each, so their kinds and their messages line up in two columns
    // however many there are and however wide the widest kind is.
    var errors = file.errors || [];
    if (!errors.length) {
      return;
    }
    var reasons = document.createElement("div");
    reasons.className = "mreasons";
    errors.forEach(function (error) {
      reasons.appendChild(chip(words(error.error_type), "ERROR"));
      reasons.appendChild(span("mreasons__text", shown(error.message)));
    });
    built.row.appendChild(reasons);
  }

  /* What the run rejected the model's own sources over — the file's
   * `validation_errors`, and only those. A file it could not read is not one
   * of these: that is an access error, and it is reported on its own row in
   * the log. Nor is a file the repository simply had nothing for, which
   * stands in the log as MISSING_DATA. */
  function renderModelErrors(model) {
    var errors = model.validation_errors || [];
    setPanelCount(el.modelErrorCount, errors.length);
    if (!errors.length) {
      // Nothing to report is the good outcome here, unlike an empty
      // inventory or an empty log, so it is drawn as a verdict rather than
      // as the plain missing-content line those two get.
      clearPanel(
        el.modelErrors,
        "No Validation Errors",
        "Every source this model was built from passed validation."
      );
      return;
    }
    el.modelErrors.textContent = "";
    errors.forEach(function (error) {
      var built = modelRow(el.modelErrors);
      built.head.appendChild(dot("error"));
      built.head.appendChild(span("mrow__name", shown(error.reason)));
      built.head.appendChild(chip(words(error.source_type), "ERROR"));

      var line = detailLine(built.row);
      line.appendChild(
        document.createTextNode(
          shown(error.source_name) + " · " + shown(error.project_platform)
        )
      );
    });
  }

  function modelRow(host) {
    var row = document.createElement("div");
    row.className = "mrow";
    var head = document.createElement("div");
    head.className = "mrow__head";
    row.appendChild(head);
    host.appendChild(row);
    return { row: row, head: head };
  }

  function detailLine(row) {
    var line = document.createElement("div");
    line.className = "mrow__detail";
    row.appendChild(line);
    return line;
  }

  // textContent throughout, as in the console: every string here comes from
  // a repository the run read, so none of it is ever parsed as markup.
  function span(className, text) {
    var node = document.createElement("span");
    node.className = className;
    node.textContent = text;
    return node;
  }

  function chip(text, status) {
    var node = span("chip", text);
    if (status) {
      node.setAttribute("data-status", status);
    }
    return node;
  }

  function dot(level, title) {
    var node = span("dot", "");
    node.setAttribute("data-level", String(level || "").toLowerCase());
    if (title) {
      node.title = title;
    }
    return node;
  }

  function emptyPanel(host, text) {
    host.textContent = "";
    host.appendChild(note("units__empty", text));
  }

  // A panel that is empty because the run found nothing to put in it, which
  // is what a good run looks like: the seal, the verdict, and what it covers.
  function clearPanel(host, title, text) {
    host.textContent = "";
    var box = document.createElement("div");
    box.className = "mclear";
    var seal = span("mclear__seal", "");
    var glyph = document.createElement("i");
    glyph.className = "lucide lucide-circle-check";
    seal.appendChild(glyph);
    box.appendChild(seal);
    box.appendChild(note("mclear__title", title));
    box.appendChild(note("mclear__note", text));
    host.appendChild(box);
  }

  function note(className, text) {
    var node = document.createElement("p");
    node.className = className;
    node.textContent = text;
    return node;
  }

  function setPanelCount(node, count) {
    node.textContent = count ? String(count) : "";
  }

  // The file marks an absent value rather than omitting it; a dash says the
  // same thing without dressing it up as data.
  function shown(value) {
    return value === 0 || (value && value !== MISSING) ? String(value) : "—";
  }

  // The file's own enums are SCREAMING_SNAKE; the chips that carry them are
  // uppercased by the stylesheet, so only the underscores need going.
  function words(value) {
    return shown(value).replace(/_/g, " ");
  }

  // The file's own ISO timestamp, in the reader's clock — left as written if
  // this browser cannot parse it.
  function generatedAt(value) {
    if (!value) {
      return "—";
    }
    var when = new Date(value);
    return isNaN(when.getTime()) ? value : when.toLocaleString();
  }

  /* ------------------------------------------------------------ remember */

  // Usernames only, and only to prefill a field. Never secrets.
  function remember(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (error) {
      /* private mode, blocked storage — the prefill is optional */
    }
  }

  function restore(input, key) {
    var saved = null;
    try {
      saved = window.localStorage.getItem(key);
    } catch (error) {
      saved = null;
    }
    if (saved) {
      input.value = saved;
    }
  }

  /* ------------------------------------------------------------- wire-up */

  function wireReveal() {
    document.addEventListener("click", function (event) {
      var button = event.target.closest
        ? event.target.closest("[data-reveal]")
        : null;
      if (!button) {
        return;
      }
      var input = $(button.getAttribute("data-reveal"));
      var icon = button.querySelector(".lucide");
      var shown = input.type === "text";
      input.type = shown ? "password" : "text";
      icon.className = shown ? "lucide lucide-eye-off" : "lucide lucide-eye";
      button.setAttribute("aria-label", shown ? "Show password" : "Hide password");
      input.focus();
    });
  }

  function wireStepper() {
    STAGES.forEach(function (key) {
      el.stepper[key].button.addEventListener("click", function () {
        if (key === state.view) {
          return;
        }
        if (key === "sources") {
          enterSources();
        } else if (key === "inventory") {
          enterInventory();
        } else if (key === "run") {
          enterProduce();
        } else if (key === "model") {
          enterModel();
        } else if (
          state.view === "inventory" ||
          state.view === "run" ||
          state.view === "model"
        ) {
          // The pickers still hold this selection; no need to refetch.
          showView("select");
        } else {
          enterSelect();
        }
      });
    });
  }

  function wireSignOut() {
    Array.prototype.forEach.call(
      document.querySelectorAll("[data-signout]"),
      function (button) {
        button.addEventListener("click", signOut);
      }
    );
  }

  function wireLogin() {
    clearOnInput([el.username, el.password], "login");

    el.loginForm.addEventListener("submit", function (event) {
      event.preventDefault();
      setMessage("login", null, "");

      if (!el.username.value || !el.password.value) {
        setMessage("login", "error", "Username and password are required.");
        (el.username.value ? el.password : el.username).focus();
        return;
      }

      setBusy(el.loginSubmit, true, "Authenticating", "Authenticate");
      request("POST", API.login, {
        username: el.username.value,
        password: el.password.value
      })
        .then(function (payload) {
          state.username = payload.username;
          state.defaults = payload.defaults;
          remember(LAST_USER_KEY, payload.username);
          el.password.value = "";
          setBusy(el.loginSubmit, false, "Authenticating", "Authenticate");
          // Sign-in ends here; the source connections are their own stage.
          enterSources();
        })
        .catch(function (error) {
          setBusy(el.loginSubmit, false, "Authenticating", "Authenticate");
          setMessage("login", "error", error.message);
          el.password.value = "";
          el.password.focus();
        });
    });
  }

  function wireSelect() {
    el.project.addEventListener("change", function () {
      setMessage("select", null, "");
      clearPlatform();
      syncSelectSubmit();
      if (!el.project.value) {
        return;
      }
      loadPlatforms(el.project.value).catch(function (error) {
        if (!handleExpired(error)) {
          setMessage("select", "error", error.message);
        }
      });
    });

    el.platform.addEventListener("change", function () {
      setMessage("select", null, "");
      clearVersion();
      syncSelectSubmit();
      if (!el.platform.value) {
        return;
      }
      loadVersions(el.project.value, el.platform.value).catch(function (error) {
        if (!handleExpired(error)) {
          setMessage("select", "error", error.message);
        }
      });
    });

    el.version.addEventListener("change", syncSelectSubmit);

    el.selectForm.addEventListener("submit", function (event) {
      event.preventDefault();
      setMessage("select", null, "");
      setBusy(el.selectSubmit, true, "Saving", "Continue");
      request("POST", API.selection, {
        project_id: el.project.value,
        platform_id: el.platform.value,
        version_id: el.version.value
      })
        .then(function (payload) {
          var changed = !tracks(state.selection, payload.selection);
          state.selection = payload.selection;
          if (changed) {
            // Produced files, the candidate and the inventory card all
            // described the context just left behind.
            forgetContext();
          }
          if (!tracks(state.activeTask, state.selection)) {
            state.activeTask = null;
            closeRunStream();
          }
          setBusy(el.selectSubmit, false, "Saving", "Continue");
          enterInventory();
        })
        .catch(function (error) {
          setBusy(el.selectSubmit, false, "Saving", "Continue");
          if (!handleExpired(error)) {
            setMessage("select", "error", error.message);
          }
        });
    });
  }

  function wireInventory() {
    el.unitFilter.addEventListener("input", paintUnits);
    el.candidateUnit.addEventListener("change", onCandidateUnitChange);
    el.candidateVersion.addEventListener("change", onCandidateVersionChange);

    // Going back to the context is the stepper's job; this card only leads
    // forward.
    el.inventoryNext.addEventListener("click", enterProduce);
  }

  function collect() {
    el.shell = $("shell");
    el.card = $("card");
    el.title = $("title");
    el.subtitle = $("subtitle");
    el.stepperList = $("stepper");
    el.stepper = {};
    STAGES.forEach(function (key) {
      var item = $("stepper-" + key);
      el.stepper[key] = { item: item, button: item.querySelector(".stepper__button") };
    });
    el.logo = $("logo");
    el.brandIcon = $("brand-icon");
    el.sessionbar = $("sessionbar");
    el.sessionbarUser = $("sessionbar-user");

    el.loginForm = $("login-form");
    el.username = $("username");
    el.password = $("password");
    el.loginSubmit = $("login-submit");

    el.sourcesGrid = $("sources-grid");
    el.sourcesSubmit = $("sources-submit");

    el.modal = $("modal");
    el.modalForm = $("modal-form");
    el.modalIcon = $("modal-icon");
    el.modalTitle = $("modal-title");
    el.modalSubmit = $("modal-submit");
    el.sourceAddress = $("source-address");
    el.sourceUsername = $("source-username");
    el.sourcePassword = $("source-password");

    el.selectForm = $("select-form");
    el.pickerPlatform = $("picker-platform");
    el.pickerVersion = $("picker-version");
    el.project = $("project");
    el.platform = $("platform");
    el.version = $("version");
    el.selectSubmit = $("select-submit");

    el.contextProject = $("context-project");
    el.contextPlatform = $("context-platform");
    el.contextVersion = $("context-version");
    el.contextCurrent = $("context-current");
    el.unitFilter = $("unit-filter");
    el.unitCount = $("unit-count");
    el.unitList = $("unit-list");
    el.candidateUnit = $("candidate-unit");
    el.candidateVersion = $("candidate-version");
    el.candidateVersionPicker = $("picker-candidate-version");
    el.candidateNote = $("candidate-note");
    el.inventoryNext = $("inventory-next");

    el.runStatus = $("run-status");
    el.runStatusValue = $("run-status-value");
    el.runSummary = $("run-summary");
    el.console = $("console");
    el.runStart = $("run-start");
    el.runCancel = $("run-cancel");
    el.runModel = $("run-model");
    el.runBack = $("run-back");
    el.runFilesPanel = $("run-files-panel");
    el.runFiles = $("run-files");
    el.runFilesEmpty = $("run-files-empty");
    el.filesProduce = $("files-produce");
    el.filesLog = $("files-log");

    el.modelContext = $("model-context");
    el.modelProject = $("model-project");
    el.modelPlatform = $("model-platform");
    el.modelVersion = $("model-version");
    el.modelCurrent = $("model-current");
    el.modelGenerated = $("model-generated");
    el.modelLoading = $("model-loading");
    el.modelGrid = $("model-grid");
    el.modelScale = $("model-scale");
    el.modelUnits = $("model-units");
    el.modelUnitCount = $("model-unit-count");
    el.modelLog = $("model-log");
    el.modelLogCount = $("model-log-count");
    el.modelErrors = $("model-errors");
    el.modelErrorCount = $("model-error-count");
    el.modelDownload = $("model-download");
  }

  collect();
  wireReveal();
  wireSignOut();
  wireStepper();
  wireLogin();
  wireSources();
  wireModal();
  wireSelect();
  wireInventory();
  wireRun();
  boot();
})();
