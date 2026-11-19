import { useMemo, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  Check,
  ChevronDown,
  CircleHelp,
  FlaskConical,
  Gauge,
  GaugeCircle,
  Info,
  LoaderCircle,
  Plus,
  Rocket,
  RotateCcw,
  Sparkles,
  Trash2,
  TriangleAlert,
} from "lucide-react";

type Mode = "equilibrium" | "rocket";
type Reactant = { species: string; moles: number };
type Result = {
  mode: Mode;
  converged: boolean;
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

  const temperatureLabel =
    mode === "rocket" ? "Chamber temperature" : equilibriumType === "HP" ? "Reactant temperature" : "Temperature";

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="CEA Studio home">
          <span className="brand-mark"><FlaskConical size={20} strokeWidth={2.2} /></span>
          <span className="brand-name">cea<span>studio</span></span>
        </a>
        <div className="topbar-center"><span className="crumb">WORKSPACE</span><span className="crumb-slash">/</span><span>New calculation</span></div>
        <div className="engine-pill"><span className="live-dot" /> NASA CEA <span className="engine-version">v3</span></div>
      </header>

      <section className="page-heading">
        <div>
          <div className="eyebrow"><Sparkles size={13} /> CHEMICAL EQUILIBRIUM WITH APPLICATIONS</div>
          <h1>Make the chemistry <span>work for you.</span></h1>
          <p>Set up a case, run the NASA CEA engine, and explore the results.</p>
        </div>
        <a className="docs-link" href="https://nasa.github.io/cea/interfaces/python_api.html" target="_blank" rel="noreferrer">
          <CircleHelp size={16} /> API reference <ArrowDownToLine className="external-icon" size={13} />
        </a>
      </section>

      <nav className="mode-tabs" aria-label="Calculation type">
        <button className={mode === "equilibrium" ? "mode-tab active" : "mode-tab"} onClick={() => { setMode("equilibrium"); setTemperature(298.15); setResult(null); }}>
          <Activity size={17} /> Equilibrium <span>Combustion &amp; mixtures</span>
        </button>
        <button className={mode === "rocket" ? "mode-tab active" : "mode-tab"} onClick={() => { setMode("rocket"); setTemperature(3500); setResult(null); }}>
          <Rocket size={17} /> Rocket performance <span>Nozzle flow &amp; Isp</span>
        </button>
      </nav>

      <div className="workspace-grid">
        <section className="panel setup-panel">
          <div className="panel-heading">
            <div className="section-index">01</div>
            <div><h2>Case setup</h2><p>Define reactants and initial conditions</p></div>
            <button className="icon-button help-button" aria-label="About case setup" title="Species names must match NASA CEA's thermodynamic database."><Info size={16} /></button>
          </div>

          <div className="field-block">
            <div className="field-label-row"><label>Reactants</label><span className="field-note">Species from CEA database</span></div>
            <div className="reactant-list">
              <div className="reactant-header"><span>SPECIES</span><span>AMOUNT · MOL</span><span /></div>
              {reactants.map((reactant, index) => (
                <div className="reactant-row" key={index}>
                  <input aria-label={`Reactant ${index + 1} species`} value={reactant.species} onChange={(event) => setReactant(index, { species: event.target.value })} placeholder="e.g. H2" />
                  <input aria-label={`Reactant ${index + 1} amount in moles`} type="number" min="0.000001" step="any" value={reactant.moles} onChange={(event) => setReactant(index, { moles: Number(event.target.value) })} />
                  <button className="remove-button" aria-label={`Remove ${reactant.species}`} disabled={reactants.length < 2} onClick={() => setReactants((current) => current.filter((_, position) => position !== index))}><Trash2 size={15} /></button>
                </div>
              ))}
              <button className="add-reactant" onClick={() => setReactants((current) => [...current, { species: "", moles: 1 }])}><Plus size={15} /> Add reactant</button>
            </div>
            <div className="preset-row"><span>QUICK START</span>{Object.entries(presets).map(([name, values]) => <button key={name} onClick={() => setReactants(values.map((item) => ({ ...item })))}>{name}</button>)}</div>
          </div>

          <div className="divider" />

          {mode === "equilibrium" && (
            <div className="field-block">
              <div className="field-label-row"><label htmlFor="equilibrium">Equilibrium constraint</label><span className="field-note">Choose the known state</span></div>
              <div className="select-wrap">
                <select id="equilibrium" value={equilibriumType} onChange={(event) => setEquilibriumType(event.target.value as "HP" | "TP")}>
                  <option value="HP">HP · Constant enthalpy &amp; pressure</option>
                  <option value="TP">TP · Constant temperature &amp; pressure</option>
                </select><ChevronDown size={16} />
              </div>
              <p className="field-hint">{equilibriumType === "HP" ? "Adiabatic equilibrium: CEA finds the final temperature." : "Isothermal equilibrium: you set the temperature below."}</p>
            </div>
          )}

          <div className="two-fields">
            <div className="field-block">
              <label htmlFor="pressure">Chamber pressure</label>
              <div className="input-with-unit"><input id="pressure" type="number" min="0.000001" step="any" value={pressure} onChange={(event) => setPressure(Number(event.target.value))} /><span>bar</span></div>
            </div>
            <div className="field-block">
              <label htmlFor="temperature">{temperatureLabel}</label>
              <div className="input-with-unit"><input id="temperature" type="number" min="1" step="any" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} /><span>K</span></div>
            </div>
          </div>

          {mode === "rocket" && (
            <div className="field-block rocket-field">
              <div className="field-label-row"><label htmlFor="exit-ratio">Exit pressure ratio</label><span className="field-note">Chamber / exit</span></div>
              <div className="input-with-unit"><input id="exit-ratio" type="number" min="1.01" step="any" value={exitPressureRatio} onChange={(event) => setExitPressureRatio(Number(event.target.value))} /><span>Pc / Pe</span></div>
            </div>
          )}

          <div className="units-note"><Info size={14} /><span>CEA uses bar, kelvin, and molar reactant amounts. No hidden unit conversions.</span></div>
          <button className="run-button" onClick={runCalculation} disabled={loading || reactants.some((item) => !item.species.trim() || !Number.isFinite(item.moles) || item.moles <= 0) || !Number.isFinite(pressure) || pressure <= 0 || !Number.isFinite(temperature) || temperature <= 0}>
            {loading ? <LoaderCircle className="spin" size={17} /> : mode === "rocket" ? <Rocket size={17} /> : <Activity size={17} />}
            {loading ? "Running CEA…" : "Run calculation"} <span>↗</span>
          </button>
        </section>

        <section className="panel results-panel">
          <div className="panel-heading result-heading">
            <div className="section-index">02</div>
            <div><h2>Results</h2><p>{result ? "Calculation complete" : "Your output will appear here"}</p></div>
            {result && <button className="export-button" onClick={downloadResult}><ArrowDownToLine size={15} /> Export JSON</button>}
          </div>

          {error && <div className="error-banner" role="alert"><TriangleAlert size={18} /><div><strong>Calculation failed</strong><span>{error}</span></div><button aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}

          {!result && !loading && !error && (
            <div className="empty-state">
              <div className="empty-art"><div className="orbit orbit-one" /><div className="orbit orbit-two" /><span><GaugeCircle size={30} /></span></div>
              <h3>Ready when you are</h3>
              <p>Configure your reactants and conditions, then run a CEA calculation to see the thermodynamic output.</p>
              <div className="empty-meta"><span><span className="tiny-dot" /> Native NASA engine</span><span>·</span><span>SI-aware outputs</span></div>
            </div>
          )}

          {loading && <div className="loading-state"><LoaderCircle className="spin" size={25} /><span>Solving with NASA CEA…</span><small>Equilibrium calculations may take a few seconds.</small></div>}

          {result && (
            <div className="result-content">
              <div className={result.converged ? "convergence good" : "convergence warning"}><span className="convergence-dot" />{result.converged ? "Converged successfully" : "Solver did not converge"}<span className="result-mode">{result.mode === "rocket" ? "ROCKET" : "EQUILIBRIUM"}</span></div>
              {result.properties && (
                <>
                  <div className="metric-grid">
                    <Metric label="Temperature" value={number(result.properties.T, 1)} unit="K" highlight />
                    <Metric label="Pressure" value={number(result.properties.P, 3)} unit="bar" />
                    <Metric label="Density" value={number(result.properties.density, 4)} unit="kg/m³" />
                    <Metric label="Specific heat ratio" value={number(result.properties.gamma_s, 4)} unit="γ" />
                  </div>
                  <div className="result-section-title"><span>THERMODYNAMIC PROPERTIES</span><span>CEA NATIVE UNITS</span></div>
                  <div className="property-list">
                    <Property label="Enthalpy" value={number(result.properties.enthalpy, 2)} unit="kJ/kg" />
                    <Property label="Entropy" value={number(result.properties.entropy, 3)} unit="kJ/(kg·K)" />
                    <Property label="Molecular weight" value={number(result.properties.MW, 3)} unit="g/mol" />
                    <Property label="Cp / Cv" value={`${number(result.properties.cp, 3)} / ${number(result.properties.cv, 3)}`} unit="kJ/(kg·K)" />
                    <Property label="Viscosity" value={number(result.properties.viscosity, 4)} unit="millipoise" />
                    <Property label="Thermal conductivity" value={number(result.properties.conductivity_eq, 4)} unit="μW/(cm·K)" />
                  </div>
                  {sortedSpecies.length > 0 && <div className="species-section">
                    <div className="result-section-title"><span>PRODUCT SPECIES</span><span>MASS FRACTION</span></div>
                    {sortedSpecies.map(([species, fraction]) => <div className="species-row" key={species}><span className="species-name">{species}</span><div className="species-bar-track"><span style={{ width: `${Math.max(1, fraction * 100)}%` }} /></div><span className="species-value">{number(fraction * 100, 2)}%</span></div>)}
                  </div>}
                </>
              )}
              {result.stations && <RocketResults stations={result.stations} />}
              <div className="result-actions"><span><Check size={14} /> Result is ready to use</span><button onClick={copyResult}>{copied ? <Check size={14} /> : <RotateCcw size={14} />}{copied ? "Copied" : "Copy result"}</button></div>
            </div>
          )}
        </section>
      </div>

      <footer className="page-footer"><span>CEA STUDIO <span className="footer-separator">·</span> POWERED BY NASA CEA V3</span><a href="https://nasa.github.io/cea/" target="_blank" rel="noreferrer">NASA CEA documentation <ArrowDownToLine size={12} /></a></footer>
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
    <div className="result-section-title"><span>NOZZLE STATIONS</span><span>CEA OUTPUT</span></div>
    <div className="station-table">
      <div className="station-row station-header"><span>Station</span><span>Pressure · bar</span><span>Temp · K</span><span>Mach</span><span>Area ratio</span></div>
      {(stations.pressure ?? []).map((value, index) => <div className="station-row" key={index}><span>{index === 0 ? "Chamber" : index === (stations.pressure?.length ?? 0) - 1 ? "Exit" : `Point ${index + 1}`}</span><span>{number(value, 3)}</span><span>{number(stations.temperature?.[index], 1)}</span><span>{number(stations.mach?.[index], 3)}</span><span>{number(stations.areaRatio?.[index], 3)}</span></div>)}
    </div>
    <p className="rocket-note"><Gauge size={14} /> Specific impulse is reported in m/s by the Python API. Divide by standard gravity for seconds.</p>
  </>;
}

export default App;
