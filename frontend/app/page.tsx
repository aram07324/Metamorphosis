import BackendStatus from "@/app/components/backend-status";
import Link from "next/link";

const overview = [
  { label: "Conversations", value: "Ready", note: "Start a chat with the local mock provider" },
  { label: "Active workflows", value: "—", note: "Automation arrives in milestone 3" },
  { label: "Runs this week", value: "—", note: "Execution history is not connected yet" },
];

export default function Home() {
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Metamorphosis home">
          <span className="brand-mark">M</span>
          <span>metamorphosis</span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <button className="workspace-picker" type="button" disabled>
          <span className="workspace-avatar">W</span>
          <span className="workspace-name">My workspace</span>
          <span className="chevron">⌄</span>
        </button>
        <nav className="navigation" aria-label="Main navigation">
          <a className="nav-item active" href="#overview" aria-current="page">
            <span className="nav-icon">⌂</span> Overview
          </a>
          <Link className="nav-item" href="/chat">
            <span className="nav-icon">✳</span> AI assistant
          </Link>
          <span className="nav-item disabled" aria-disabled="true">
            <span className="nav-icon">◇</span> Workflows <span className="soon">SOON</span>
          </span>
          <span className="nav-item disabled" aria-disabled="true">
            <span className="nav-icon">⇄</span> Integrations <span className="soon">SOON</span>
          </span>
        </nav>
        <div className="sidebar-bottom">
          <div className="avatar">B</div>
          <div className="profile">
            <strong>Local development</strong>
            <span>Personal workspace</span>
          </div>
          <span className="settings-icon" aria-hidden="true">⚙</span>
        </div>
      </aside>

      <section className="main-panel" id="overview">
        <header className="topbar">
          <span className="breadcrumb">Workspace <span>/</span> Overview</span>
          <div className="topbar-right">
            <BackendStatus />
            <span className="environment-tag">LOCAL</span>
          </div>
        </header>

        <div className="content">
          <div className="welcome-row">
            <div>
              <p className="eyebrow">YOUR AUTOMATION WORKSPACE</p>
              <h1>A fresh start.</h1>
              <p className="welcome-copy">
                Chat with the local mock assistant now. Workflows and integrations are planned
                for later milestones.
              </p>
            </div>
            <div className="date-chip"><span className="sparkle">✳</span> Built for your ideas</div>
          </div>

          <div className="stat-grid" aria-label="Workspace overview">
            {overview.map((item) => (
              <article className="stat-card" key={item.label}>
                <div className="stat-heading">{item.label}<span className="stat-dot" /></div>
                <strong className="stat-value">{item.value}</strong>
                <span className="stat-note">{item.note}</span>
              </article>
            ))}
          </div>

          <section className="launch-card" aria-labelledby="launch-title">
            <div className="launch-art" aria-hidden="true">
              <div className="orbit orbit-one" />
              <div className="orbit orbit-two" />
              <div className="orbit-core">✳</div>
              <span className="orbit-star star-one">✦</span>
              <span className="orbit-star star-two">✧</span>
            </div>
            <div className="launch-content">
              <span className="phase-label">MILESTONE 2 · CHAT ENGINE</span>
              <h2 id="launch-title">Your assistant is ready to chat.</h2>
              <p>
                Conversations save locally and responses stream from a deterministic mock provider.
                Ollama can be configured later without changing your chat history.
              </p>
              <div className="milestone-progress" aria-label="Milestone 2 of 5">
                <span className="progress-track"><span className="progress-fill progress-fill-two" /></span>
                <span>02 <span className="progress-divider">/</span> 05</span>
              </div>
              <Link className="dashboard-chat-link" href="/chat">Open AI assistant <span>→</span></Link>
            </div>
          </section>

          <footer className="footer-note">
            <span className="footer-icon">◈</span>
            <span>Local-first by design. No AI provider or paid service is required to get started.</span>
            <a href="http://127.0.0.1:8001/docs" target="_blank" rel="noreferrer">API docs <span>↗</span></a>
          </footer>
        </div>
      </section>
    </main>
  );
}
