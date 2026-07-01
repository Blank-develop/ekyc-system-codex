import { LockKeyhole, LogOut, RefreshCw, ScrollText, ShieldAlert, ShieldCheck, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import logoUrl from "../assets/logo.png";
import { AuditEvent, AuditVerifyResponse, AuthUserInfo, UserProfile, api } from "../lib/api";
import { clearAuthToken, getAuthToken, setAuthToken } from "../lib/auth";

type Status = { kind: "error" | "success"; message: string } | null;

export function AdminConsole() {
  const [user, setUser] = useState<AuthUserInfo | null>(null);
  const [booting, setBooting] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<Status>(null);
  const [profiles, setProfiles] = useState<UserProfile[]>([]);
  const [loadingProfiles, setLoadingProfiles] = useState(false);
  const [audit, setAudit] = useState<AuditEvent[]>([]);
  const [auditVerify, setAuditVerify] = useState<AuditVerifyResponse | null>(null);

  const signOut = useCallback((message?: string) => {
    clearAuthToken();
    setUser(null);
    setProfiles([]);
    setAudit([]);
    setAuditVerify(null);
    if (message) setStatus({ kind: "error", message });
  }, []);

  const loadAudit = useCallback(async () => {
    try {
      const [list, verify] = await Promise.all([api.listAudit(50), api.verifyAudit()]);
      setAudit(list.events);
      setAuditVerify(verify);
    } catch {
      // Non-fatal: the profiles view is the primary console. Leave audit empty.
    }
  }, []);

  const loadProfiles = useCallback(async () => {
    setLoadingProfiles(true);
    setStatus(null);
    try {
      const res = await api.listProfiles();
      setProfiles(res.profiles);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Failed to load profiles.";
      if (/401|token|privileg/i.test(message)) signOut("Session expired. Please sign in again.");
      else setStatus({ kind: "error", message });
    } finally {
      setLoadingProfiles(false);
    }
  }, [signOut]);

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
    if (user) {
      void loadProfiles();
      void loadAudit();
    }
  }, [user, loadProfiles, loadAudit]);

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

  const handleDelete = async (profile: UserProfile) => {
    if (!window.confirm(`Permanently delete the profile for "${profile.user_id}"? This cannot be undone.`)) {
      return;
    }
    try {
      await api.deleteProfile(profile.user_id);
      setStatus({ kind: "success", message: `Deleted profile for ${profile.user_id}.` });
      await loadProfiles();
      await loadAudit();
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : "Delete failed." });
    }
  };

  const handlePurge = async () => {
    if (!window.confirm("Purge all profiles past the retention window (LALIGENCE_PROFILE_RETENTION_DAYS)?")) {
      return;
    }
    try {
      const res = await api.purgeExpiredProfiles();
      setStatus({
        kind: "success",
        message: res.deleted_count
          ? `Purged ${res.deleted_count} expired profile(s).`
          : "No profiles were past the retention window (or retention is disabled)."
      });
      await loadProfiles();
      await loadAudit();
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

  // --- Authenticated console -------------------------------------------------
  return (
    <main className="admin-shell admin-shell-wide">
      <header className="admin-topbar">
        <div className="admin-brand">
          <img src={logoUrl} alt="Kyron" className="admin-logo-sm" />
          <div>
            <strong>Verification console</strong>
            <span className="admin-muted">
              <ShieldCheck size={13} /> {user.username} · {user.role}
            </span>
          </div>
        </div>
        <button className="admin-ghost" onClick={() => signOut()}>
          <LogOut size={15} /> Sign out
        </button>
      </header>

      <section className="admin-card">
        <div className="admin-section-head">
          <h2>Enrolled profiles <span className="admin-count">{profiles.length}</span></h2>
          <div className="admin-actions">
            <button className="admin-ghost" onClick={loadProfiles} disabled={loadingProfiles}>
              <RefreshCw size={14} /> Refresh
            </button>
            <button className="admin-ghost admin-danger" onClick={handlePurge}>
              Purge expired
            </button>
          </div>
        </div>

        {status && (
          <p className={`admin-status ${status.kind === "error" ? "admin-status-error" : "admin-status-ok"}`}>
            {status.message}
          </p>
        )}

        {loadingProfiles ? (
          <p className="admin-muted">Loading profiles…</p>
        ) : profiles.length === 0 ? (
          <p className="admin-muted">No enrolled profiles.</p>
        ) : (
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Name</th>
                  <th>Nationality</th>
                  <th>Enrolled</th>
                  <th>Consent</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {profiles.map((p) => (
                  <tr key={p.face_id}>
                    <td>{p.user_id}</td>
                    <td>{p.full_name ?? "—"}</td>
                    <td>{p.nationality ?? "—"}</td>
                    <td>{p.enrolled_at ? new Date(p.enrolled_at).toLocaleDateString() : "—"}</td>
                    <td>{p.consent_version ?? "—"}</td>
                    <td>
                      <button className="admin-icon-danger" onClick={() => handleDelete(p)} title="Delete profile">
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
            <button className="admin-ghost" onClick={loadAudit}>
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
                    <td>{new Date(e.event_time).toLocaleString()}</td>
                    <td>{e.event_type}</td>
                    <td>{e.action}</td>
                    <td>{e.actor ?? "—"}</td>
                    <td>{e.subject ?? "—"}</td>
                    <td><code className="admin-hash">{e.entry_hash.slice(0, 10)}…</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
