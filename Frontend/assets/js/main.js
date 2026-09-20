"use strict";

(function () {

  var sidebarStorageKey = "INOUTX.sidebarMini";
  var themeStorageKey = "adminHMD.colorTheme";
  var desktopMedia = "(min-width: 992px)";


  /* =========================================================
     READY
  ========================================================= */

  function onReady(callback) {

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", callback);
      return;
    }

    callback();
  }


  /* =========================================================
     HELPERS
  ========================================================= */

  function isDesktop() {
    return window.matchMedia(desktopMedia).matches;
  }


  function canUseStorage() {

    try {

      var testKey = sidebarStorageKey + ".test";

      window.localStorage.setItem(testKey, "1");
      window.localStorage.removeItem(testKey);

      return true;

    } catch (error) {

      return false;

    }
  }


  function getSavedMiniState(storageAvailable) {

    if (!storageAvailable) {
      return false;
    }

    return window.localStorage.getItem(sidebarStorageKey) === "true";
  }


  function saveMiniState(storageAvailable, isMini) {

    if (storageAvailable) {

      window.localStorage.setItem(
        sidebarStorageKey,
        String(isMini)
      );

    }
  }


  function getPreferredTheme(storageAvailable) {

    var savedTheme =
      storageAvailable
        ? window.localStorage.getItem(themeStorageKey)
        : "";

    if (savedTheme === "dark" || savedTheme === "light") {
      return savedTheme;
    }

    if (
      window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
    ) {
      return "dark";
    }

    return "light";
  }


  /* =========================================================
     MAIN
  ========================================================= */

  onReady(function () {

    var body = document.body;

    var sidebarToggle =
      document.querySelector("[data-sidebar-toggle]");

    var themeToggles =
      document.querySelectorAll("[data-theme-toggle]");

    var themeIcons =
      document.querySelectorAll("[data-theme-icon]");

    var closeButtons =
      document.querySelectorAll("[data-sidebar-close]");

    var sidebarLinks =
      document.querySelectorAll(".sidebar-nav .nav-link");

    var mediaQuery =
      window.matchMedia(desktopMedia);

    var storageAvailable =
      canUseStorage();

    loadCurrentUser();


    /* =======================================================
       FORM VALIDATION
    ======================================================= */

    function initValidation() {

      var forms =
        document.querySelectorAll(".needs-validation");

      Array.prototype.forEach.call(forms, function (form) {

        form.addEventListener("submit", function (event) {

          /*
           * IMPORTANT:
           * Login form is handled separately below.
           */
          if (form.id === "loginForm") {
            return;
          }

          if (!form.checkValidity()) {

            event.preventDefault();
            event.stopPropagation();

          }

          form.classList.add("was-validated");

        });

      });

    }


    /* =======================================================
       LOGIN
    ======================================================= */

    function initLogin() {

      var loginForm =
        document.getElementById("loginForm");

      /*
       * If this is not the login page,
       * simply do nothing.
       */
      if (!loginForm) {
        return;
      }


      var emailInput =
        document.getElementById("loginEmail");

      var passwordInput =
        document.getElementById("loginPassword");

      var rememberMe =
        document.getElementById("rememberMe");

      var loginButton =
        document.getElementById("loginButton");

      var loginButtonText =
        document.getElementById("loginButtonText");

      var loginIcon =
        document.getElementById("loginIcon");

      var loginError =
        document.getElementById("loginError");

      var loginSuccess =
        document.getElementById("loginSuccess");


      /*
       * Make absolutely sure the normal HTML
       * form submission does NOT happen.
       */
      loginForm.addEventListener("submit", async function (event) {

        event.preventDefault();
        event.stopPropagation();

        console.log("INOUTX: Login form submitted");


        /* ---------------------------------------------------
           VALIDATION
        --------------------------------------------------- */

        if (!loginForm.checkValidity()) {

          loginForm.classList.add("was-validated");

          console.log(
            "INOUTX: Login validation failed"
          );

          return;
        }


        loginForm.classList.add("was-validated");


        /* ---------------------------------------------------
           VALUES
        --------------------------------------------------- */

        var email =
          emailInput.value.trim().toLowerCase();

        var password =
          passwordInput.value;


        /* ---------------------------------------------------
           CLEAR OLD MESSAGES
        --------------------------------------------------- */

        if (loginError) {

          loginError.textContent = "";
          loginError.classList.add("d-none");

        }

        if (loginSuccess) {

          loginSuccess.textContent = "";
          loginSuccess.classList.add("d-none");

        }


        /* ---------------------------------------------------
           BUTTON LOADING
        --------------------------------------------------- */

        if (loginButton) {
          loginButton.disabled = true;
        }

        if (loginIcon) {
          loginIcon.className =
            "bi bi-arrow-repeat";
        }

        if (loginButtonText) {
          loginButtonText.textContent =
            "Signing in...";
        }


        console.log(
          "INOUTX: Sending login request..."
        );

        console.log(
          "INOUTX: Email =",
          email
        );


        try {

          /* ===============================================
             FLASK LOGIN API
          =============================================== */

          var response =
            await fetch("/api/login", {

              method: "POST",

              headers: {
                "Content-Type": "application/json"
              },

              credentials: "include",

              body: JSON.stringify({

                email: email,
                password: password

              })

            });


          console.log(
            "INOUTX: API status =",
            response.status
          );


          /* ------------------------------------------------
             READ RESPONSE
          ------------------------------------------------ */

          var data;

          try {

            data =
              await response.json();

          } catch (jsonError) {

            console.error(
              "INOUTX: Invalid server response",
              jsonError
            );

            throw new Error(
              "Server returned an invalid response."
            );

          }


          console.log(
            "INOUTX: API response =",
            data
          );


          /* ------------------------------------------------
             LOGIN FAILED
          ------------------------------------------------ */

          if (!response.ok || !data.success) {

            var errorMessage =
              data.error ||
              "Invalid email or password.";

            console.error(
              "INOUTX: Login failed:",
              errorMessage
            );


            if (loginError) {

              loginError.textContent =
                errorMessage;

              loginError.classList.remove(
                "d-none"
              );

            }


            if (loginButton) {
              loginButton.disabled = false;
            }

            if (loginIcon) {

              loginIcon.className =
                "bi bi-box-arrow-in-right";

            }

            if (loginButtonText) {

              loginButtonText.textContent =
                "Sign In";

            }

            return;
          }


          /* ------------------------------------------------
             LOGIN SUCCESS
          ------------------------------------------------ */

          console.log(
            "================================="
          );

          console.log(
            "INOUTX LOGIN SUCCESS"
          );

          console.log(
            "User:",
            data.user
          );

          console.log(
            "================================="
          );


          /* ------------------------------------------------
             REMEMBER EMAIL
          ------------------------------------------------ */

          if (
            rememberMe &&
            rememberMe.checked
          ) {

            try {

              localStorage.setItem(
                "inoutx_remember_email",
                email
              );

            } catch (storageError) {

              console.warn(
                "Unable to save remembered email."
              );

            }

          } else {

            try {

              localStorage.removeItem(
                "inoutx_remember_email"
              );

            } catch (storageError) {

              // Ignore
            }

          }


          /* ------------------------------------------------
             SUCCESS MESSAGE
          ------------------------------------------------ */

          if (loginSuccess) {

            loginSuccess.textContent =
              "Login successful. Redirecting...";

            loginSuccess.classList.remove(
              "d-none"
            );

          }


          /* ------------------------------------------------
             SUCCESS BUTTON
          ------------------------------------------------ */

          if (loginIcon) {

            loginIcon.className =
              "bi bi-check-circle";

          }

          if (loginButtonText) {

            loginButtonText.textContent =
              "Login Successful";

          }


          /* ------------------------------------------------
             DASHBOARD REDIRECT
          ------------------------------------------------ */

          console.log(
            "INOUTX: Redirecting to dashboard..."
          );


          setTimeout(function () {

            /*
             * Your dashboard is currently assumed
             * to be index.html.
             */
            window.location.replace(
              "index.html"
            );

          }, 500);


        } catch (error) {

          console.error(
            "INOUTX: Login request error:",
            error
          );


          if (loginError) {

            loginError.textContent =
              "Unable to connect to the INOUTX server. Make sure Flask is running.";

            loginError.classList.remove(
              "d-none"
            );

          }


          if (loginButton) {
            loginButton.disabled = false;
          }

          if (loginIcon) {

            loginIcon.className =
              "bi bi-box-arrow-in-right";

          }

          if (loginButtonText) {

            loginButtonText.textContent =
              "Sign In";

          }

        }

      });


      /* =====================================================
         REMEMBERED EMAIL
      ===================================================== */

      try {

        var rememberedEmail =
          localStorage.getItem(
            "inoutx_remember_email"
          );

        if (
          rememberedEmail &&
          emailInput
        ) {

          emailInput.value =
            rememberedEmail;

          if (rememberMe) {
            rememberMe.checked = true;
          }

        }

      } catch (storageError) {

        console.warn(
          "INOUTX: LocalStorage unavailable."
        );

      }

    }


    /* =======================================================
       TABLE SEARCH
    ======================================================= */

    function initTableSearch() {

      var searchInputs =
        document.querySelectorAll(
          "[data-table-search]"
        );

      Array.prototype.forEach.call(
        searchInputs,
        function (input) {

          var tableId =
            input.getAttribute(
              "data-table-search"
            );

          var table =
            document.getElementById(tableId);

          if (!table) {
            return;
          }

          input.addEventListener(
            "input",
            function () {

              var query =
                input.value
                  .trim()
                  .toLowerCase();

              var rows =
                table.querySelectorAll(
                  "tbody tr"
                );

              Array.prototype.forEach.call(
                rows,
                function (row) {

                  row.hidden =
                    query !== "" &&
                    row.textContent
                      .toLowerCase()
                      .indexOf(query) === -1;

                }
              );

            }
          );

        }
      );

    }


    /* =======================================================
       THEME
    ======================================================= */

    function updateThemeControls(theme) {

      var nextTheme =
        theme === "dark"
          ? "light"
          : "dark";

      var label =
        "Switch to " +
        nextTheme +
        " mode";

      var iconClass =
        theme === "dark"
          ? "bi bi-sun"
          : "bi bi-moon-stars";


      Array.prototype.forEach.call(
        themeToggles,
        function (button) {

          button.setAttribute(
            "aria-label",
            label
          );

          button.setAttribute(
            "title",
            label
          );

        }
      );


      Array.prototype.forEach.call(
        themeIcons,
        function (icon) {

          icon.className =
            iconClass;

        }
      );

    }


    function applyTheme(theme) {

      document.documentElement.setAttribute(
        "data-theme",
        theme
      );

      document.documentElement.setAttribute(
        "data-bs-theme",
        theme
      );


      if (storageAvailable) {

        window.localStorage.setItem(
          themeStorageKey,
          theme
        );

      }


      updateThemeControls(theme);

    }


    function initThemeToggle() {

      applyTheme(
        getPreferredTheme(
          storageAvailable
        )
      );


      Array.prototype.forEach.call(
        themeToggles,
        function (button) {

          button.addEventListener(
            "click",
            function () {

              var currentTheme =
                document.documentElement
                  .getAttribute("data-theme") ===
                "dark"
                  ? "dark"
                  : "light";


              applyTheme(
                currentTheme === "dark"
                  ? "light"
                  : "dark"
              );

            }
          );

        }
      );

    }


    /* =======================================================
       USER PROFILE
    ======================================================= */

    function initUserProfile() {

      var user = window.adminHMDUser || {};


      var sidebarNameEl =
        document.querySelector(
          ".sidebar-user strong"
        );

      var sidebarWorkspaceEl =
        document.querySelector(
          ".sidebar-user small"
        );

      var sidebarAvatar =
        document.querySelector(
          ".sidebar-user .avatar-img"
        );

      var profileNameEls =
        document.querySelectorAll(
          ".profile-name"
        );

      var profileAvatarEls =
        document.querySelectorAll(
          ".profile-button .avatar-img, .profile-button img"
        );


      if (sidebarNameEl) {
        sidebarNameEl.textContent =
          user.name || "";
      }


      if (sidebarWorkspaceEl) {
        sidebarWorkspaceEl.textContent =
          user.role || "";
      }


      if (
        sidebarAvatar &&
        user.avatar
      ) {

        sidebarAvatar.src =
          user.avatar;

        sidebarAvatar.alt =
          user.name;

      }


      Array.prototype.forEach.call(
        profileNameEls,
        function (el) {

          el.textContent =
            user.name || "";

        }
      );


      Array.prototype.forEach.call(
        profileAvatarEls,
        function (img) {

          if (user.avatar) {
            img.src = user.avatar;
          }

          if (user.name) {
            img.alt = user.name;
          }

        }
      );

    }


    /* =======================================================
       INITIALIZE
    ======================================================= */

    initValidation();

    initLogin();

    initTableSearch();

    initThemeToggle();

    initUserProfile();


    /* =======================================================
       SIDEBAR
    ======================================================= */

    if (!sidebarToggle) {
      return;
    }


    function setClass(
      element,
      className,
      enabled
    ) {

      if (enabled) {
        element.classList.add(className);
      } else {
        element.classList.remove(className);
      }

    }


    function setToggleExpanded() {

      var expanded =
        isDesktop()
          ? !body.classList.contains(
              "sidebar-mini"
            )
          : body.classList.contains(
              "sidebar-open"
            );


      sidebarToggle.setAttribute(
        "aria-expanded",
        String(expanded)
      );

    }


    function closeMobileSidebar() {

      body.classList.remove(
        "sidebar-open"
      );

      setToggleExpanded();

    }


    function toggleSidebar() {

      if (isDesktop()) {

        body.classList.toggle(
          "sidebar-mini"
        );

        saveMiniState(
          storageAvailable,
          body.classList.contains(
            "sidebar-mini"
          )
        );

      } else {

        body.classList.toggle(
          "sidebar-open"
        );

      }


      setToggleExpanded();

    }


    function addCloseHandlers(items) {

      Array.prototype.forEach.call(
        items,
        function (item) {

          item.addEventListener(
            "click",
            function () {

              if (!isDesktop()) {
                closeMobileSidebar();
              }

            }
          );

        }
      );

    }


    if (
      getSavedMiniState(
        storageAvailable
      ) &&
      isDesktop()
    ) {

      body.classList.add(
        "sidebar-mini"
      );

    }


    sidebarToggle.addEventListener(
      "click",
      toggleSidebar
    );

    addCloseHandlers(
      closeButtons
    );

    addCloseHandlers(
      sidebarLinks
    );

    setToggleExpanded();


    function handleBreakpointChange() {

      if (isDesktop()) {

        body.classList.remove(
          "sidebar-open"
        );

        setClass(
          body,
          "sidebar-mini",
          getSavedMiniState(
            storageAvailable
          )
        );

      } else {

        body.classList.remove(
          "sidebar-mini"
        );

      }


      setToggleExpanded();

    }


    if (mediaQuery.addEventListener) {

      mediaQuery.addEventListener(
        "change",
        handleBreakpointChange
      );

    } else if (mediaQuery.addListener) {

      mediaQuery.addListener(
        handleBreakpointChange
      );

    }

  });

})();

// =========================================================
// INOUTX CURRENT USER
// =========================================================

async function loadCurrentUser() {

    const userNameElement =
        document.getElementById("currentUserName");

    const initialsElement =
        document.getElementById("currentUserInitials");

    const roleElement =
      document.getElementById("currentUserRole");

    // Page doesn't contain the user panel
    if (!userNameElement) {
        return;
    }

    try {

        const response = await fetch(
            "/api/me",
            {
                method: "GET",
                credentials: "include",
                headers: {
                    "Accept": "application/json"
                }
            }
        );

        const data = await response.json();

        if (!response.ok || !data.success || !data.user) {

            userNameElement.textContent = "";

            if (initialsElement) {
            initialsElement.textContent = "";
          }

          if (roleElement) {
            roleElement.textContent = "";
            }

            return;
        }


        const user = data.user;

        const name =
            String(user.name || "").trim();

        const email =
            String(user.email || "").trim();


        // -------------------------------------------------
        // DISPLAY NAME
        // -------------------------------------------------

        userNameElement.textContent =
            name || email || "";


        // -------------------------------------------------
        // GENERATE INITIALS
        // -------------------------------------------------

        if (initialsElement) {

            let initials = "";

            if (name) {

                const parts =
                    name
                        .split(/\s+/)
                        .filter(Boolean);

                if (parts.length === 1) {

                    initials =
                        parts[0]
                            .substring(0, 2)
                            .toUpperCase();

                } else {

                    initials =
                        (
                            parts[0][0] +
                            parts[parts.length - 1][0]
                        ).toUpperCase();

                }
            }

            initialsElement.textContent =
                initials;
        }


        if (roleElement) {

          roleElement.textContent =
            String(user.role || "").trim();

        }

    } catch (error) {

        console.error(
            "Failed to load current user:",
            error
        );

        userNameElement.textContent =
            "";

    }
}

