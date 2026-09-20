import { useEffect, useRef, useState } from "react";

const pageNames = new Set([
  "index.html",
  "login.html",
  "register.html",
  "forgot-password.html",
  "profile.html",
  "staff-vehicles.html",
  "vehicle.html",
  "visitor.html",
  "download.html",
  "camera.html",
  "404.html",
  "500.html"
]);

function pageForLocation() {
  const name = window.location.pathname.split("/").filter(Boolean).pop() || "index.html";
  return pageNames.has(name) ? name : "404.html";
}

function executeScripts(container) {
  const scripts = [...container.querySelectorAll("script")];

  scripts.forEach((oldScript) => {
    const script = document.createElement("script");

    [...oldScript.attributes].forEach(({ name, value }) => {
      script.setAttribute(name, name === "src" ? value.replace(/^\.\.\/assets\//, "/assets/") : value);
    });

    script.textContent = oldScript.textContent;
    oldScript.replaceWith(script);
  });
}

function syncPageHead(pageDocument) {
  document.querySelectorAll("[data-react-page-head]").forEach((element) => element.remove());

  [...pageDocument.head.querySelectorAll("link[rel=stylesheet], style")].forEach((source) => {
    const element = source.cloneNode(true);
    element.dataset.reactPageHead = "true";

    if (element.tagName === "LINK") {
      element.href = element.href.replace(`${window.location.origin}/html/`, `${window.location.origin}/`);
    }

    document.head.appendChild(element);
  });
}

export default function App() {
  const containerRef = useRef(null);
  const [page, setPage] = useState(pageForLocation);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function loadPage() {
      setError("");

      try {
        const response = await fetch(`/html/${page}`);
        if (!response.ok) throw new Error(`Unable to load ${page}`);

        const markup = await response.text();
        const documentFragment = new DOMParser().parseFromString(markup, "text/html");

        if (cancelled || !containerRef.current) return;

        document.title = documentFragment.title || "INOUTX";
        syncPageHead(documentFragment);
        document.body.className = documentFragment.body.className;
        containerRef.current.innerHTML = documentFragment.body.innerHTML;
        executeScripts(containerRef.current);
      } catch (loadError) {
        if (!cancelled) setError(loadError.message);
      }
    }

    loadPage();

    return () => {
      cancelled = true;
      if (containerRef.current) containerRef.current.replaceChildren();
      document.querySelectorAll("[data-react-page-head]").forEach((element) => element.remove());
      document.body.className = "";
    };
  }, [page]);

  useEffect(() => {
    function handleNavigation(event) {
      const link = event.target.closest("a");
      if (!link || link.target === "_blank" || link.origin !== window.location.origin) return;

      const url = new URL(link.href);
      const name = url.pathname.split("/").filter(Boolean).pop();
      if (!pageNames.has(name)) return;

      event.preventDefault();
      window.history.pushState({}, "", `/${name}`);
      setPage(name);
    }

    function handlePopState() {
      setPage(pageForLocation());
    }

    document.addEventListener("click", handleNavigation);
    window.addEventListener("popstate", handlePopState);

    return () => {
      document.removeEventListener("click", handleNavigation);
      window.removeEventListener("popstate", handlePopState);
    };
  }, []);

  if (error) {
    return <main className="auth-body"><p>{error}</p></main>;
  }

  return <div ref={containerRef} />;
}
