import {
  ChevronLeft,
  ChevronRight,
  Fingerprint,
  LayoutDashboard,
  ListChecks,
  LockKeyhole,
  LogOut,
  RefreshCw,
  ScrollText,
  Search,
  ShieldAlert,
  ShieldCheck,
  Trash2,
  Images,
  X
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import logoUrl from "../assets/logo.png";
import {
  AdminOverview,
  Attempt,
  AuditEvent,
  AuditVerifyResponse,
  AuthUserInfo,
  SessionEvidence,
  UserProfile,
  api
} from "../lib/api";
import { clearAuthToken, getAuthToken, setAuthToken } from "../lib/auth";
import {
  formatLocalDate,
  formatLocalDateTime,
  formatLocalTime,
  localTimeZoneLabel
} from "../lib/dateTime";

type Status = { kind: "error" | "success"; message: string } | null;
type Tab = "overview" | "attempts" | "faceids" | "audit";
const ATTEMPT_PAGE_SIZE = 20;


const EVIDENCE_STEPS: Array<{ key: string; label: string }> = [
  { key: "document", label: "Document" },
  { key: "active_liveness", label: "Active liveness" },
  { key: "hand_gesture", label: "Hand gesture" },
  { key: "selfie", label: "Selfie" }
];

/** Lazily fetches one frame; frames are auth-fetched and access-logged server-side. */
function EvidenceThumb({ frameId, label }: { frameId: string; label: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    api
      .evidenceFrameUrl(frameId)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        revoked = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [frameId]);

  if (failed) return <div className="evidence-thumb evidence-thumb-missing">unavailable</div>;
  if (!url) return <div className="evidence-thumb evidence-thumb-loading" />;
  return (
    <a className="evidence-thumb" href={url} target="_blank" rel="noreferrer" title={`${label} — open full size`}>
      <img src={url} alt={label} />
    </a>
  );
}

function EvidenceViewer({ sessionId, onClose }: { sessionId: string; onClose: () => void }) {
  const [data, setData] = useState<SessionEvidence | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .sessionEvidence(sessionId)
      .then((result) => !cancelled && setData(result))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Could not load evidence."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const frames = data?.frames ?? [];

  return (
    <div className="evidence-backdrop" role="dialog" aria-modal="true" aria-label="Crossing evidence">
      <div className="evidence-panel">
        <header className="evidence-head">
          <div>
            <p className="admin-eyebrow">Crossing evidence</p>
            <h3>
              <code className="admin-hash">{sessionId.slice(0, 8)}…</code>
            </h3>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label="Close evidence">
            <X size={20} />
          </button>
        </header>

        {loading && <p className="admin-muted">Loading evidence…</p>}
        {error && <p className="form-error">{error}</p>}

        {!loading && !error && (
          <div className="evidence-body">
            {frames.length === 0 && (
              <p className="admin-muted">
                No frames retained for this session. Evidence capture is enabled per deployment
                (LALIGENCE_EVIDENCE_ENABLED).
              </p>
            )}

            {EVIDENCE_STEPS.map(({ key, label }) => {
              const stepFrames = frames.filter((frame) => frame.step === key);
              if (stepFrames.length === 0) return null;
              return (
                <section className="evidence-step" key={key}>
                  <h4>
                    {label} <span className="admin-muted">({stepFrames.length})</span>
                  </h4>
                  <div className="evidence-grid">
                    {stepFrames.map((frame) =>
                      frame.available ? (
                        <figure key={frame.id}>
                          <EvidenceThumb frameId={frame.id} label={`${label} ${frame.sequence + 1}`} />
                          <figcaption>
                            {frame.label ? `${frame.label} · ` : ""}
                            {Math.round(frame.byte_size / 1024)} KB
                            {frame.encrypted && <span title="Encrypted at rest"> · 🔒</span>}
                          </figcaption>
                        </figure>
                      ) : (
                        <figure key={frame.id}>
                          <div className="evidence-thumb evidence-thumb-missing">expired</div>
                          <figcaption>media disposed</figcaption>
                        </figure>
                      )
                    )}
                  </div>
                </section>
              );
            })}

            {(data?.events.length ?? 0) > 0 && (
              <section className="evidence-step">
                <h4>
                  Action timeline <span className="admin-muted">({localTimeZoneLabel})</span>
                </h4>
                <ol className="evidence-timeline">
                  {data!.events.map((event, index) => (
                    <li key={index}>
                      <span className="evidence-time">
                        {formatLocalTime(event.occurred_at)}
                      </span>
                      <span className="evidence-action">
                        {event.step} · {event.action}
                      </span>
                      {event.outcome && (
                        <span className={`attempt-badge attempt-badge-${event.outcome}`}>{event.outcome}</span>
                      )}
                      {event.reason_codes.length > 0 && (
                        <span className="admin-muted"> {event.reason_codes.join(", ")}</span>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}

            <section className="evidence-step">
              <h4>
                Access history{" "}
                <span className="admin-muted">
                  (who viewed this traveller · {localTimeZoneLabel})
                </span>
              </h4>
              {(data?.access_log.length ?? 0) === 0 ? (
                <p className="admin-muted">No prior access recorded.</p>
              ) : (
                <ol className="evidence-timeline">
                  {data!.access_log.slice(0, 12).map((entry, index) => (
                    <li key={index}>
                      <span className="evidence-time">
                        {formatLocalDateTime(entry.occurred_at)}
                      </span>
                      <span className="evidence-action">
                        {entry.actor} · {entry.action}
                      </span>
                      {entry.client_ip && <span className="admin-muted"> {entry.client_ip}</span>}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

export function AdminConsole() {
  const [user, setUser] = useState<AuthUserInfo | null>(null);
  const [booting, setBooting] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [tab, setTab] = useState<Tab>("overview");

  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(false);

  const [profiles, setProfiles] = useState<UserProfile[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);

  const [attempts, setAttempts] = useState<Attempt[]>([]);
  const [attemptsTotal, setAttemptsTotal] = useState(0);
  const [loadingAttempts, setLoadingAttempts] = useState(false);
  const [decisionFilter, setDecisionFilter] = useState("");
  const [userFilter, setUserFilter] = useState("");
  const [attemptOffset, setAttemptOffset] = useState(0);
  const [evidenceSession, setEvidenceSession] = useState<string | null>(null);

  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [auditVerify, setAuditVerify] = useState<AuditVerifyResponse | null>(null);

  const signOut = useCallback((message?: string) => {
    clearAuthToken();
    setUser(null);
    setOverview(null);
    setProfiles([]);
    setAttempts([]);
    setAttemptsTotal(0);
    setAudit([]);
    setAuditVerify(null);
    if (message) setStatus({ kind: "error", message });
  }, []);

  const handleAuthError = useCallback(
    (error: unknown, fallback: string) => {
      const message = error instanceof Error ? error.message : fallback;
      if (/401|token|privileg/i.test(message)) {
        signOut("Session expired. Please sign in again.");
        return true;
      }
      setStatus({ kind: "error", message });
      return false;
    },
    [signOut]
  );

  const loadOverview = useCallback(async () => {
    setLoadingOverview(true);
    try {
      setOverview(await api.adminOverview());
    } catch (error) {
      handleAuthError(error, "Failed to load overview.");
    } finally {
      setLoadingOverview(false);
    }
  }, [handleAuthError]);

  const loadProfiles = useCallback(async () => {
    setLoadingProfiles(true);
    try {
      const res = await api.listProfiles();
      setProfiles(res.profiles);
    } catch (error) {
      handleAuthError(error, "Failed to load Face IDs.");
    } finally {
      setLoadingProfiles(false);
    }
  }, [handleAuthError]);

  const loadAttempts = useCallback(
    async (offsetOverride?: number) => {
      const offset = offsetOverride ?? attemptOffset;
      setLoadingAttempts(true);
      try {
        const res = await api.listAttempts({
          limit: ATTEMPT_PAGE_SIZE,
          offset,
          decision: decisionFilter || undefined,
          userId: userFilter.trim() || undefined
        });
        setAttempts(res.attempts);
        setAttemptsTotal(res.total);
      } catch (error) {
        handleAuthError(error, "Failed to load attempts.");
      } finally {
        setLoadingAttempts(false);
      }
    },
    [attemptOffset, decisionFilter, userFilter, handleAuthError]
  );

  const loadAudit = useCallback(async () => {
    try {
      const [list, verify] = await Promise.all([api.listAudit(50), api.verifyAudit()]);
      setAudit(list.events);
      setAuditVerify(verify);
    } catch {
      // Non-fatal: audit is a supplementary tab.
    }
  }, []);

  // Resume an existing session on load.
  useEffect(() => {
    (async () => {
      if (!getAuthToken()) {
        setBooting(false);
        return;
      }
      try {
        setUser(await api.me());
      } catch {
        clearAuthToken();
      } finally {
        setBooting(false);
      }
    })();
  }, []);

  useEffect(() => {
    if (!user) return;
    void loadOverview();
    void loadProfiles();
    void loadAttempts(0);
    void loadAudit();
    // Only re-run when the signed-in user changes; filters/pagination are
    // handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (!user) return;
    void loadAttempts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [attemptOffset]);

  const applyAttemptFilters = () => {
    setAttemptOffset(0);
    void loadAttempts(0);
  };

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setStatus(null);
    try {
      const token = await api.login(username.trim(), password);
      setAuthToken(token.access_token);
      const me = await api.me();
      setUser(me);
      setPassword("");
    } catch (error) {
      clearAuthToken();
      setStatus({
        kind: "error",
        message: error instanceof Error ? error.message : "Sign in failed."
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteProfile = async (profile: UserProfile) => {
    if (!window.confirm(`Permanently delete the profile for "${profile.user_id}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteProfile(profile.user_id);
      setStatus({ kind: "success", message: `Deleted profile for ${profile.user_id}.` });
      await Promise.all([loadProfiles(), loadOverview(), loadAudit()]);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Delete failed." });
    }
  };

  const handlePurgeProfiles = async () => {
    if (!window.confirm("Purge all Face IDs past the retention window (LALIGENCE_PROFILE_RETENTION_DAYS)?")) {
      return;
    }
    try {
      const res = await api.purgeExpiredProfiles();
      setStatus({
        kind: "success",
        message: res.deleted_count
          ? `Purged ${res.deleted_count} expired Face ID(s).`
          : "No Face IDs were past the retention window (or retention is disabled)."
      });
      await Promise.all([loadProfiles(), loadOverview(), loadAudit()]);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Purge failed." });
    }
  };

  const handlePurgeAttempts = async () => {
    if (!window.confirm("Purge all attempts past the retention window (LALIGENCE_ATTEMPT_RETENTION_DAYS)?")) {
      return;
    }
    try {
      const res = await api.purgeExpiredAttempts();
      setStatus({
        kind: "success",
        message: res.deleted_count
          ? `Purged ${res.deleted_count} expired attempt(s).`
          : "No attempts were past the retention window (or retention is disabled)."
      });
      await Promise.all([loadAttempts(0), loadOverview()]);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Purge failed." });
    }
  };

  if (booting) {
    return (
      <main className="admin-shell">
        <p className="admin-muted">Loading…</p>
      </main>
    );
  }

  // --- Login screen ----------------------------------------------------------
  if (!user) {
    return (
      <main className="admin-shell">
        <form className="admin-card admin-login" onSubmit={handleLogin}>
          <img src={logoUrl} alt="Kyron" className="admin-logo" />
          <h1 className="admin-title">
            <LockKeyhole size={18} /> Staff sign in
          </h1>
          <p className="admin-muted">Operator access to the verification console.</p>

          <label className="admin-field">
            <span>Username</span>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label className="admin-field">
            <span>Password</span>
            <input
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>

          {status?.kind === "error" && <p className="admin-status admin-status-error">{status.message}</p>}

          <button className="admin-primary" type="submit" disabled={submitting}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
          <a className="admin-back" href="#">← Back to verification</a>
        </form>
      </main>
    );
  }

  // --- Authenticated portal ----------------------------------------------------
  const page = Math.floor(attemptOffset / ATTEMPT_PAGE_SIZE) + 1;
  const pageCount = Math.max(1, Math.ceil(attemptsTotal / ATTEMPT_PAGE_SIZE));

  return (
    <main className="admin-shell admin-shell-wide">
      <header className="admin-topbar">
        <div className="admin-brand">
          <img src={logoUrl} alt="Kyron" className="admin-logo-sm" />
          <div>
            <strong>Admin portal</strong>
            <span className="admin-muted">
              <ShieldCheck size={13} /> {user.username} · {user.role}
            </span>
          </div>
        </div>
        <button className="admin-ghost" onClick={() => signOut()}>
          <LogOut size={15} /> Sign out
        </button>
      </header>

      <nav className="admin-tabs" role="tablist">
        <button
          role="tab"
          className={`admin-tab ${tab === "overview" ? "active" : ""}`}
          onClick={() => setTab("overview")}
        >
          <LayoutDashboard size={15} /> Overview
        </button>
        <button
          role="tab"
          className={`admin-tab ${tab === "attempts" ? "active" : ""}`}
          onClick={() => setTab("attempts")}
        >
          <ListChecks size={15} /> Attempts
          {attemptsTotal > 0 && <span className="admin-tab-count">{attemptsTotal}</span>}
        </button>
        <button
          role="tab"
          className={`admin-tab ${tab === "faceids" ? "active" : ""}`}
          onClick={() => setTab("faceids")}
        >
          <Fingerprint size={15} /> Face IDs
          {profiles.length > 0 && <span className="admin-tab-count">{profiles.length}</span>}
        </button>
        <button role="tab" className={`admin-tab ${tab === "audit" ? "active" : ""}`} onClick={() => setTab("audit")}>
          <ScrollText size={15} /> Audit Log
        </button>
      </nav>

      {status && (
        <p className={`admin-status admin-status-page ${status.kind === "error" ? "admin-status-error" : "admin-status-ok"}`}>
          {status.message}
        </p>
      )}

      {tab === "overview" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>Overview</h2>
            <button className="admin-ghost" onClick={() => void loadOverview()} disabled={loadingOverview}>
              <RefreshCw size={14} /> Refresh
            </button>
          </div>

          {loadingOverview && !overview ? (
            <p className="admin-muted">Loading overview…</p>
          ) : overview ? (
            <>
              <div className="admin-stat-grid">
                <div className="admin-stat-card">
                  <span className="admin-stat-label">Total eKYC attempts</span>
                  <span className="admin-stat-value">{overview.attempts.total}</span>
                  <div className="admin-stat-breakdown">
                    <span className="attempt-badge attempt-badge-passed">{overview.attempts.passed} passed</span>
                    <span className="attempt-badge attempt-badge-pending">{overview.attempts.pending} pending</span>
                    <span className="attempt-badge attempt-badge-rejected">{overview.attempts.rejected} rejected</span>
                  </div>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-label">Enrolled Face IDs</span>
                  <span className="admin-stat-value">{overview.enrolled_face_ids}</span>
                  <span className="admin-muted">Retention: {overview.profile_retention_days > 0 ? `${overview.profile_retention_days} days` : "indefinite"}</span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-label">Audit log integrity</span>
                  <span className={`admin-integrity ${overview.audit_chain_ok ? "ok" : "broken"}`} style={{ marginTop: 4 }}>
                    {overview.audit_chain_ok ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
                    {overview.audit_log_enabled
                      ? overview.audit_chain_ok
                        ? `Verified · ${overview.audit_entries} entries`
                        : "Tampering detected"
                      : "Disabled"}
                  </span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-label">Attempt log retention</span>
                  <span className="admin-stat-value">
                    {overview.attempt_retention_days > 0 ? `${overview.attempt_retention_days}d` : "∞"}
                  </span>
                  <span className="admin-muted">LALIGENCE_ATTEMPT_RETENTION_DAYS</span>
                </div>
              </div>
              <p className="admin-muted admin-overview-hint">
                Every eKYC attempt is recorded automatically (decision, per-step results, no raw images or
                biometrics). See the Attempts tab for the full list, and Face IDs for who has enrolled.
              </p>
            </>
          ) : (
            <p className="admin-muted">No data yet.</p>
          )}
        </section>
      )}

      {tab === "attempts" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>
              eKYC Attempts <span className="admin-count">{attemptsTotal}</span>
            </h2>
            <div className="admin-actions">
              <button className="admin-ghost" onClick={() => void loadAttempts()} disabled={loadingAttempts}>
                <RefreshCw size={14} /> Refresh
              </button>
              <button className="admin-ghost admin-danger" onClick={handlePurgeAttempts}>
                Purge expired
              </button>
            </div>
          </div>

          <div className="admin-filters">
            <select
              className="admin-select"
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              aria-label="Filter by decision"
            >
              <option value="">All decisions</option>
              <option value="passed">Passed</option>
              <option value="pending">Pending</option>
              <option value="rejected">Rejected</option>
            </select>
            <label className="admin-search">
              <Search size={14} />
              <input
                type="text"
                placeholder="Filter by user ID"
                value={userFilter}
                onChange={(e) => setUserFilter(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && applyAttemptFilters()}
              />
            </label>
            <button className="admin-ghost" onClick={applyAttemptFilters}>
              Apply
            </button>
          </div>

          {loadingAttempts ? (
            <p className="admin-muted">Loading attempts…</p>
          ) : attempts.length === 0 ? (
            <p className="admin-muted">No eKYC attempts recorded yet.</p>
          ) : (
            <>
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>Session</th>
                      <th>User</th>
                      <th>Decision</th>
                      <th>Document</th>
                      <th>Steps</th>
                      <th>Face match</th>
                      <th>Client IP</th>
                      <th>Updated</th>
                    </tr>
                  </thead>
                  <tbody>
                    {attempts.map((a) => (
                      <tr key={a.session_id}>
                        <td>
                          <button
                            type="button"
                            className="evidence-open"
                            onClick={() => setEvidenceSession(a.session_id)}
                            title="View retained evidence for this crossing"
                          >
                            <Images size={13} />
                            <code className="admin-hash">{a.session_id.slice(0, 8)}…</code>
                          </button>
                        </td>
                        <td>{a.user_id}</td>
                        <td>
                          <span className={`attempt-badge attempt-badge-${a.decision}`} title={a.reason_codes.join(", ") || undefined}>
                            {a.decision}
                          </span>
                        </td>
                        <td>
                          {a.document_type ?? "—"}
                          {a.document_status && <span className="admin-muted"> ({a.document_status})</span>}
                        </td>
                        <td>
                          <span
                            className={`admin-step-dot ${a.active_liveness_passed ? "on" : ""}`}
                            title="Active liveness"
                          >
                            AL
                          </span>
                          <span className={`admin-step-dot ${a.hand_challenge_passed ? "on" : ""}`} title="Hand gesture">
                            HG
                          </span>
                          <span
                            className={`admin-step-dot ${a.passive_liveness_passed ? "on" : ""}`}
                            title="Passive liveness"
                          >
                            PL
                          </span>
                          <span className={`admin-step-dot ${a.contact_confirmed ? "on" : ""}`} title="Contact confirmed">
                            CC
                          </span>
                        </td>
                        <td>{a.face_match_score != null ? a.face_match_score.toFixed(2) : "—"}</td>
                        <td>{a.client_ip ?? "—"}</td>
                        <td title={`${a.updated_at} UTC`}>{formatLocalDateTime(a.updated_at)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="admin-pagination">
                <button
                  className="admin-ghost"
                  disabled={attemptOffset === 0}
                  onClick={() => setAttemptOffset(Math.max(0, attemptOffset - ATTEMPT_PAGE_SIZE))}
                >
                  <ChevronLeft size={14} /> Prev
                </button>
                <span className="admin-muted">
                  Page {page} of {pageCount}
                </span>
                <button
                  className="admin-ghost"
                  disabled={attemptOffset + ATTEMPT_PAGE_SIZE >= attemptsTotal}
                  onClick={() => setAttemptOffset(attemptOffset + ATTEMPT_PAGE_SIZE)}
                >
                  Next <ChevronRight size={14} />
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {tab === "faceids" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>
              Enrolled Face IDs <span className="admin-count">{profiles.length}</span>
            </h2>
            <div className="admin-actions">
              <button className="admin-ghost" onClick={() => void loadProfiles()} disabled={loadingProfiles}>
                <RefreshCw size={14} /> Refresh
              </button>
              <button className="admin-ghost admin-danger" onClick={handlePurgeProfiles}>
                Purge expired
              </button>
            </div>
          </div>

          {loadingProfiles ? (
            <p className="admin-muted">Loading Face IDs…</p>
          ) : profiles.length === 0 ? (
            <p className="admin-muted">No enrolled Face IDs.</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Face ID</th>
                    <th>User</th>
                    <th>Name</th>
                    <th>Nationality</th>
                    <th>Enrolled</th>
                    <th>Last login</th>
                    <th>Consent</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {profiles.map((p) => (
                    <tr key={p.face_id}>
                      <td>
                        <code className="admin-hash" title={p.face_id}>
                          {p.face_id.slice(0, 8)}…
                        </code>
                      </td>
                      <td>{p.user_id}</td>
                      <td>{p.full_name ?? "—"}</td>
                      <td>{p.nationality ?? "—"}</td>
                      <td>{formatLocalDate(p.enrolled_at)}</td>
                      <td>{formatLocalDateTime(p.last_login_at)}</td>
                      <td>{p.consent_version ?? "—"}</td>
                      <td>
                        <button className="admin-icon-danger" onClick={() => handleDeleteProfile(p)} title="Delete this Face ID">
                          <Trash2 size={15} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {tab === "audit" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>
              <ScrollText size={16} style={{ verticalAlign: "-2px", marginRight: 6 }} />
              Audit log
            </h2>
            <div className="admin-actions">
              {auditVerify && (
                <span className={`admin-integrity ${auditVerify.ok ? "ok" : "broken"}`}>
                  {auditVerify.ok ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
                  {auditVerify.ok
                    ? `Chain verified · ${auditVerify.entries} entries`
                    : `Tampering detected at #${auditVerify.broken_at}`}
                </span>
              )}
              <button className="admin-ghost" onClick={() => void loadAudit()}>
                <RefreshCw size={14} /> Re-verify
              </button>
            </div>
          </div>

          {audit.length === 0 ? (
            <p className="admin-muted">No audit events yet.</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>Time</th>
                    <th>Type</th>
                    <th>Action</th>
                    <th>Actor</th>
                    <th>Subject</th>
                    <th>Hash</th>
                  </tr>
                </thead>
                <tbody>
                  {audit.map((e) => (
                    <tr key={e.seq}>
                      <td>{e.seq}</td>
                      <td>{formatLocalDateTime(e.event_time)}</td>
                      <td>{e.event_type}</td>
                      <td>{e.action}</td>
                      <td>{e.actor ?? "—"}</td>
                      <td>{e.subject ?? "—"}</td>
                      <td>
                        <code className="admin-hash">{e.entry_hash.slice(0, 10)}…</code>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {evidenceSession && (
        <EvidenceViewer sessionId={evidenceSession} onClose={() => setEvidenceSession(null)} />
      )}
    </main>
  );
}
