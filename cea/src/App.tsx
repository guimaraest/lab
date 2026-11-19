import { useMemo, useState, type ChangeEvent } from "react";

type Mode = "equilibrium" | "rocket" | "deck";
type Reactant = { species: string; moles: number };
type Result = {
  mode: "equilibrium" | "rocket";
  converged: boolean;
  equilibriumType?: "HP" | "TP";
  properties?: Record<string, number>;
  massFractions?: Record<string, number>;
  stations?: Record<string, number[]>;
};

const initialReactants: Reactant[] = [
  { species: "H2", moles: 2 },
  { species: "O2", moles: 1 },
];

const presets: Record<string, Reactant[]> = {
  "H2 + O2": initialReactants,
  "CH4 + O2": [
    { species: "CH4", moles: 1 },
    { species: "O2", moles: 2 },
  ],
};

const number = (value: unknown, digits = 2) =>
  typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat(undefined, { maximumFractionDigits: digits }).format(value)
    : "—";

function App() {
  const [mode, setMode] = useState<Mode>("equilibrium");
  const [reactants, setReactants] = useState<Reactant[]>(initialReactants);
  const [equilibriumType, setEquilibriumType] = useState<"HP" | "TP">("HP");
  const [pressure, setPressure] = useState(1);
  const [temperature, setTemperature] = useState(298.15);
  const [exitPressureRatio, setExitPressureRatio] = useState(40);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [deckInput, setDeckInput] = useState("");
  const [deckOutput, setDeckOutput] = useState("");
  const [deckName, setDeckName] = useState("cea-case");
  const [deckLoading, setDeckLoading] = useState(false);

  const sortedSpecies = useMemo(
    () =>
      Object.entries(result?.massFractions ?? {})
        .filter(([, fraction]) => fraction > 1e-7)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 12),
    [result],
  );

  const setReactant = (index: number, patch: Partial<Reactant>) =>
    setReactants((current) =>
      current.map((item, position) => (position === index ? { ...item, ...patch } : item)),
    );

  async function runCalculation() {
    setLoading(true);
    setError("");
    setResult(null);
    try {
      const response = await fetch("/api/solve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          mode,
          reactants,
          pressure,
          temperature,
          equilibriumType,
          exitPressureRatio,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "The calculation could not be completed.");
      setResult(body as Result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The calculation could not be completed.");
    } finally {
      setLoading(false);
    }
  }

  function downloadResult() {
    if (!result) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `cea-${result.mode}-result.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function copyResult() {
    if (!result) return;
    await navigator.clipboard.writeText(JSON.stringify(result, null, 2));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  async function loadDeckFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    event.currentTarget.value = "";
    if (file.size > 512 * 1024) {
      setError("Input file must be 512 KiB or smaller.");
      return;
    }
    try {
      setDeckInput(await file.text());
      setDeckName(file.name.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9._-]/g, "_") || "cea-case");
      setDeckOutput("");
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read the input file.");
    }
  }

  async function runDeck() {
    setDeckLoading(true);
    setDeckOutput("");
    setError("");
    try {
      const response = await fetch("/api/deck", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input: deckInput }),
      });
      const body = await response.json() as { output?: string; error?: string };
      if (!response.ok) throw new Error(body.error ?? "CEA could not run this input deck.");
      if (typeof body.output !== "string") throw new Error("CEA returned no output file.");
      setDeckOutput(body.output);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "CEA could not run this input deck.");
    } finally {
      setDeckLoading(false);
    }
  }

  function downloadText(filename: string, text: string, type: string) {
    const url = URL.createObjectURL(new Blob([text], { type }));
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  }

  function downloadDeckInput() {
    downloadText(`${deckName}.inp`, deckInput, "text/plain");
  }

  function downloadDeckOutput() {
    downloadText(`${deckName}.out`, deckOutput, "text/plain");
  }

  const temperatureLabel =
    mode === "rocket" ? "Chamber temperature" : equilibriumType === "HP" ? "Reactant temperature" : "Temperature";

  return (
    <main className="app-shell">
      <header className="topbar">
        <strong>NASA CEA</strong>
        <a href="https://nasa.github.io/cea/interfaces/python_api.html" target="_blank" rel="noreferrer">Python API reference</a>
      </header>

      <section className="page-heading">
        <h1>CEA calculator</h1>
      </section>

      <nav className="mode-tabs" aria-label="Calculation type">
        <button className={mode === "equilibrium" ? "mode-tab active" : "mode-tab"} aria-pressed={mode === "equilibrium"} onClick={() => { setMode("equilibrium"); setTemperature(298.15); setResult(null); }}>
          Equilibrium
        </button>
        <button className={mode === "rocket" ? "mode-tab active" : "mode-tab"} aria-pressed={mode === "rocket"} onClick={() => { setMode("rocket"); setTemperature(3500); setResult(null); }}>
          Rocket performance
        </button>
        <button className={mode === "deck" ? "mode-tab active" : "mode-tab"} aria-pressed={mode === "deck"} onClick={() => { setMode("deck"); setError(""); }}>
          Input / output files
        </button>
      </nav>

      {mode === "deck" ? (
        <div className="workspace-grid deck-grid">
          <section className="panel deck-panel">
            <div className="panel-heading">
              <h2>Input deck (.inp)</h2>
              <div className="deck-actions">
                <label className="file-button">Open file<input type="file" accept=".inp,.txt" onChange={loadDeckFile} /></label>
                <button className="export-button" onClick={downloadDeckInput} disabled={!deckInput}>Save .inp</button>
              </div>
            </div>
            <textarea className="deck-textarea" aria-label="CEA input deck" spellCheck={false} value={deckInput} onChange={(event) => setDeckInput(event.target.value)} placeholder="Paste a legacy CEA input deck here, or open a .inp file." />
            <p className="deck-hint">Maximum input size: 512 KiB.</p>
            <button className="run-button" onClick={runDeck} disabled={deckLoading || !deckInput.trim()}>
              {deckLoading ? "Running CEA…" : "Run input deck"}
            </button>
          </section>

          <section className="panel deck-panel">
            <div className="panel-heading">
              <h2>Output (.out)</h2>
              {deckOutput && <button className="export-button" onClick={downloadDeckOutput}>Save .out</button>}
            </div>
            {error && <div className="error-banner" role="alert">{error}</div>}
            {deckLoading && <p className="loading-state">Waiting for CEA output…</p>}
            <textarea className="deck-textarea deck-output" aria-label="CEA output file" spellCheck={false} readOnly value={deckOutput} placeholder="CEA output will appear here after the deck runs." />
          </section>
        </div>
      ) : (
      <div className="workspace-grid">
        <section className="panel setup-panel">
          <h2>Inputs</h2>

          <div className="field-block">
            <label>Reactants</label>
            <div className="reactant-list">
              <div className="reactant-header"><span>Species</span><span>Moles</span><span /></div>
              {reactants.map((reactant, index) => (
                <div className="reactant-row" key={index}>
                  <input aria-label={`Reactant ${index + 1} species`} value={reactant.species} onChange={(event) => setReactant(index, { species: event.target.value })} placeholder="e.g. H2" />
                  <input aria-label={`Reactant ${index + 1} amount in moles`} type="number" min="0.000001" step="any" value={reactant.moles} onChange={(event) => setReactant(index, { moles: Number(event.target.value) })} />
                  <button className="remove-button" aria-label={`Remove ${reactant.species}`} disabled={reactants.length < 2} onClick={() => setReactants((current) => current.filter((_, position) => position !== index))}>Remove</button>
                </div>
              ))}
              <button className="add-reactant" onClick={() => setReactants((current) => [...current, { species: "", moles: 1 }])}>Add reactant</button>
            </div>
            <div className="preset-row"><span>Presets</span>{Object.entries(presets).map(([name, values]) => <button key={name} onClick={() => setReactants(values.map((item) => ({ ...item })))}>{name}</button>)}</div>
          </div>

          {mode === "equilibrium" && (
            <div className="field-block">
              <label htmlFor="equilibrium">Equilibrium constraint</label>
              <div className="select-wrap">
                <select id="equilibrium" value={equilibriumType} onChange={(event) => setEquilibriumType(event.target.value as "HP" | "TP")}>
                  <option value="HP">HP · Constant enthalpy &amp; pressure</option>
                  <option value="TP">TP · Constant temperature &amp; pressure</option>
                </select>
              </div>
              <p className="field-hint">{equilibriumType === "HP" ? "Adiabatic equilibrium: CEA finds the final temperature." : "Isothermal equilibrium: you set the temperature below."}</p>
            </div>
          )}

          <div className="two-fields">
            <div className="field-block">
              <label htmlFor="pressure">{mode === "rocket" ? "Chamber pressure" : "Pressure"}</label>
              <div className="input-with-unit"><input id="pressure" type="number" min="0.000001" step="any" value={pressure} onChange={(event) => setPressure(Number(event.target.value))} /><span>bar</span></div>
            </div>
            <div className="field-block">
              <label htmlFor="temperature">{temperatureLabel}</label>
              <div className="input-with-unit"><input id="temperature" type="number" min="1" step="any" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /><span>K</span></div>
            </div>
          </div>

          {mode === "rocket" && (
            <div className="field-block rocket-field">
              <label htmlFor="exit-ratio">Chamber / exit pressure ratio</label>
              <div className="input-with-unit"><input id="exit-ratio" type="number" min="1.01" step="any" value={exitPressureRatio} onChange={(event) => setExitPressureRatio(Number(event.target.value))} /><span>Pc / Pe</span></div>
            </div>
          )}

          <p className="units-note">Units: pressure in bar, temperature in K, reactant amounts in mol.</p>
          <button className="run-button" onClick={runCalculation} disabled={loading || reactants.some((item) => !item.species.trim() || !Number.isFinite(item.moles) || item.moles <= 0) || !Number.isFinite(pressure) || pressure <= 0 || !Number.isFinite(temperature) || temperature <= 0}>
            {loading ? "Calculating…" : "Run calculation"}
          </button>
        </section>

        <section className="panel results-panel">
          <div className="panel-heading result-heading">
            <h2>Results</h2>
            {result && <button className="export-button" onClick={downloadResult}>Download JSON</button>}
          </div>

          {error && <div className="error-banner" role="alert"><strong>Calculation failed:</strong> {error} <button aria-label="Dismiss error" onClick={() => setError("")}>Dismiss</button></div>}

          {!result && !loading && !error && (
            <p className="empty-state">No results. Enter inputs and run a calculation.</p>
          )}

          {loading && <p className="loading-state">Calculating…</p>}

          {result && (
            <div className="result-content">
              <p className="convergence">{result.converged ? "Converged" : "Not converged"} · {result.mode === "rocket" ? "Rocket performance" : `Equilibrium ${result.equilibriumType ?? equilibriumType}`}</p>
              {result.properties && (
                <>
                  <div className="metric-grid">
                    <Metric label="Temperature" value={number(result.properties.T, 1)} unit="K" highlight />
                    <Metric label="Pressure" value={number(result.properties.P, 3)} unit="bar" />
                    <Metric label="Density" value={number(result.properties.density, 4)} unit="kg/m³" />
                    <Metric label="Specific heat ratio" value={number(result.properties.gamma_s, 4)} unit="γ" />
                  </div>
                  <div className="result-section-title"><span>Thermodynamic properties</span><span>CEA units</span></div>
                  <div className="property-list">
                    <Property label="Enthalpy" value={number(result.properties.enthalpy, 2)} unit="kJ/kg" />
                    <Property label="Entropy" value={number(result.properties.entropy, 3)} unit="kJ/(kg·K)" />
                    <Property label="Molecular weight" value={number(result.properties.MW, 3)} unit="g/mol" />
                    <Property label="Cp / Cv" value={`${number(result.properties.cp, 3)} / ${number(result.properties.cv, 3)}`} unit="kJ/(kg·K)" />
                    <Property label="Viscosity" value={number(result.properties.viscosity, 4)} unit="millipoise" />
                    <Property label="Thermal conductivity" value={number(result.properties.conductivity_eq, 4)} unit="μW/(cm·K)" />
                  </div>
                  {sortedSpecies.length > 0 && <div className="species-section">
                    <div className="result-section-title"><span>Product species</span><span>Mass fraction</span></div>
                    <div className="species-table">
                      {sortedSpecies.map(([species, fraction]) => <div className="species-row" key={species}><span className="species-name">{species}</span><span className="species-value">{number(fraction * 100, 4)}%</span></div>)}
                    </div>
                  </div>}
                </>
              )}
              {result.stations && <RocketResults stations={result.stations} />}
              <div className="result-actions"><button onClick={copyResult}>{copied ? "Copied" : "Copy JSON"}</button></div>
            </div>
          )}
        </section>
      </div>
      )}
    </main>
  );
}

function Metric({ label, value, unit, highlight = false }: { label: string; value: string; unit: string; highlight?: boolean }) {
  return <div className={highlight ? "metric-card highlight" : "metric-card"}><span>{label}</span><strong>{value}</strong><small>{unit}</small></div>;
}

function Property({ label, value, unit }: { label: string; value: string; unit: string }) {
  return <div className="property-row"><span>{label}</span><strong>{value}</strong><small>{unit}</small></div>;
}

function RocketResults({ stations }: { stations: Record<string, number[]> }) {
  const first = (key: string) => stations[key]?.[0];
  const last = (key: string) => stations[key]?.at(-1);
  return <>
    <div className="metric-grid rocket-metrics">
      <Metric label="Specific impulse" value={number(last("isp"), 1)} unit="m/s" highlight />
      <Metric label="Vacuum specific impulse" value={number(last("ispVacuum"), 1)} unit="m/s" />
      <Metric label="Characteristic velocity" value={number(first("cStar"), 1)} unit="m/s" />
      <Metric label="Thrust coefficient" value={number(last("thrustCoefficient"), 3)} unit="Cf" />
    </div>
    <h3>Nozzle stations</h3>
    <div className="station-table">
      <table>
        <thead><tr><th>Station</th><th>Pressure (bar)</th><th>Temp (K)</th><th>Mach</th><th>Area ratio</th></tr></thead>
        <tbody>{(stations.pressure ?? []).map((value, index) => <tr key={index}><td>{index === 0 ? "Chamber" : index === (stations.pressure?.length ?? 0) - 1 ? "Exit" : `Point ${index + 1}`}</td><td>{number(value, 3)}</td><td>{number(stations.temperature?.[index], 1)}</td><td>{number(stations.mach?.[index], 3)}</td><td>{number(stations.areaRatio?.[index], 3)}</td></tr>)}</tbody>
      </table>
    </div>
    <p className="rocket-note">Specific impulse is reported in m/s. Divide by standard gravity to get seconds.</p>
  </>;
}

export default App;
