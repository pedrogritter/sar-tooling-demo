import React, { useCallback, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import { fetchCurrentJob, fetchScene, startMeasureJob } from "@/api";
import { Preview } from "@/preview/Preview";
import { RunPanel } from "@/run/RunPanel";
import { ResultsPanel } from "@/results/ResultsPanel";
import type { JobResult, ResultsPanelProps, SceneResponse } from "@/types";
import "@/styles.css";

const limitLine =
  "A row is a bright return, and the page has not named a ship.";

installClientErrorReporting();

function App() {
  const [scene, setScene] = useState<SceneResponse | null>(null);
  const [sceneError, setSceneError] = useState<string | null>(null);
  const [sceneLoading, setSceneLoading] = useState(true);
  const [results, setResults] = useState<ResultsPanelProps>({
    measurement: null,
    briefing_html: null,
    overview_url: null,
  });

  useEffect(() => {
    let active = true;

    async function loadScene() {
      try {
        const nextScene = await fetchScene();

        if (!active) {
          return;
        }

        setScene(nextScene);
        setResults(sceneResults(nextScene));
        setSceneError(null);
      } catch (error) {
        if (active) {
          setSceneError(errorMessage(error));
        }
      } finally {
        if (active) {
          setSceneLoading(false);
        }
      }
    }

    void loadScene();

    return () => {
      active = false;
    };
  }, []);

  const handleJobDone = useCallback((result: JobResult) => {
    setResults({
      measurement: result.measurement,
      briefing_html: result.briefing_html,
      overview_url: result.overview_url,
    });
  }, []);

  return (
    <main className="scene">
      <header className="scene__header">
        <p className="scene__kicker">ICEYE open data - one spotlight frame</p>
        <h1 className="scene__title">25 de Abril bridge</h1>
        {scene ? <p className="scene__id">{scene.scene_id}</p> : null}
      </header>

      <p className="scene__limit" role="note">
        {limitLine}
      </p>

      <div className="scene__regions">
        <Preview scene={scene} loading={sceneLoading} error={sceneError} />
        <section className="scene__run" aria-label="Measurement run">
          <RunPanel
            fetchCurrentJob={fetchCurrentJob}
            onJobDone={handleJobDone}
            startMeasureJob={startMeasureJob}
          />
        </section>
        <section className="scene__results" aria-label="Measurement results">
          <ResultsPanel
            briefing_html={results.briefing_html}
            measurement={results.measurement}
            overview_url={results.overview_url}
          />
        </section>
      </div>
    </main>
  );
}

function sceneResults(scene: SceneResponse): ResultsPanelProps {
  return {
    measurement: scene.measurement,
    briefing_html: scene.briefing_html,
    overview_url: scene.overview_url,
  };
}

function installClientErrorReporting() {
  const report = (message: unknown, source: unknown) => {
    const body = JSON.stringify({
      message: String(message ?? ""),
      source: String(source ?? ""),
    });

    void fetch("/client-error", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    }).catch(() => undefined);
  };

  window.addEventListener("error", (event) => {
    report(event.message, event.filename);
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason as unknown;
    const message =
      reason && typeof reason === "object" && "message" in reason
        ? reason.message
        : reason;

    report(message, "unhandledrejection");
  });
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Scene metadata could not be loaded.";
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
