import { useState } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { GlobePage }      from "./pages/GlobePage";
import { TopicUniverse }  from "./pages/TopicUniverse";
import { GraphPage }      from "./pages/GraphPage";
import { BenchmarkPage }  from "./pages/BenchmarkPage";
import { ResearchMap }    from "./pages/ResearchMap";
import { TrendingPage }   from "./pages/TrendingPage";
import { ResearcherDNA }  from "./pages/ResearcherDNA";
import { ProgressPage }   from "./pages/ProgressPage";
import { LeaderboardPage } from "./pages/LeaderboardPage";
import { TopBar }          from "./components/TopBar";
import type { Researcher } from "./data/researchers";

export default function App() {
  const [selected, setSelected]       = useState<Researcher | null>(null);
  const [visibleCount, setVisibleCount] = useState(0);

  return (
    <BrowserRouter>
      <div style={{ width: "100vw", height: "100vh", background: "#000005", position: "relative" }}>

        {/* Unified top bar: logo + search + nav tabs + count */}
        <TopBar
          onSelect={setSelected}
          visibleCount={visibleCount}
        />

        <Routes>
          <Route
            path="/"
            element={
              <GlobePage
                selected={selected}
                onSelect={setSelected}
                visibleCount={visibleCount}
                onCountChange={setVisibleCount}
              />
            }
          />
          <Route
            path="/universe"
            element={
              <TopicUniverse
                selected={selected}
                onSelect={setSelected}
              />
            }
          />
          <Route
            path="/graph"
            element={
              <GraphPage
                selected={selected}
                onSelect={setSelected}
              />
            }
          />
          <Route
            path="/benchmarks"
            element={<BenchmarkPage />}
          />
          <Route
            path="/map"
            element={<ResearchMap />}
          />
          <Route
            path="/trending"
            element={<TrendingPage />}
          />
          <Route
            path="/researcher/:id"
            element={<ResearcherDNA />}
          />
          <Route
            path="/progress"
            element={<ProgressPage />}
          />
          <Route
            path="/leaderboard"
            element={<LeaderboardPage />}
          />
        </Routes>
      </div>
    </BrowserRouter>
  );
}
