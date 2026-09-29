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
import { KyronMark, KyronWordmark } from "./KyronMark";
import { LanguageSwitch } from "./LanguageSwitch";
import {
  AdminOverview,
  Attempt,
  AuditEvent,
  AuditVerifyResponse,
  AuthUserInfo,
  SessionEvidence,
  UserProfile,
  WatchlistHit,
  WatchlistSubject,
  WatchlistSummary,
  api
} from "../lib/api";
import { clearAuthToken, getAuthToken, setAuthToken } from "../lib/auth";
import { statusLabel } from "../lib/lao";
import { L } from "../lib/i18n";
import {
  formatLocalDate,
  formatLocalDateTime,
  formatLocalTime,
  localTimeZoneLabel
} from "../lib/dateTime";

type Status = { kind: "error" | "success"; message: string } | null;
type Tab = "overview" | "attempts" | "watchlist" | "faceids" | "audit";
const ATTEMPT_PAGE_SIZE = 20;


const EVIDENCE_STEPS: Array<{ key: string; label: string }> = [
  { key: "document", get label() { return L("ເອກະສານ", "Document"); } },
  { key: "active_liveness", get label() { return L("ກວດໃບໜ້າຈິງ", "Active liveness"); } },
  { key: "hand_gesture", get label() { return L("ທ່າທາງມື", "Hand gesture"); } },
  { key: "selfie", get label() { return L("ເຊວຟີ", "Selfie"); } }
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

  if (failed) return <div className="evidence-thumb evidence-thumb-missing">{L("ບໍ່ມີຮູບ", "unavailable")}</div>;
  if (!url) return <div className="evidence-thumb evidence-thumb-loading" />;
  return (
    <a className="evidence-thumb" href={url} target="_blank" rel="noreferrer" title={L(`${label} — ເປີດຂະໜາດເຕັມ`, `${label} — open full size`)}>
      <img src={url} alt={label} />
    </a>
  );
}

/** Lazily fetches an auth-protected watchlist image (enrolment photo or probe). */
function WatchlistPhoto({
  fetcher,
  caption
}: {
  fetcher: () => Promise<string>;
  caption: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let revoked: string | null = null;
    let cancelled = false;
    fetcher()
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <figure className="watchlist-photo">
      {failed ? (
        <div className="watchlist-photo-box watchlist-photo-missing">{L("ບໍ່ມີຮູບ", "no image")}</div>
      ) : url ? (
        <a href={url} target="_blank" rel="noreferrer" className="watchlist-photo-box">
          <img src={url} alt={caption} />
        </a>
      ) : (
        <div className="watchlist-photo-box watchlist-photo-loading" />
      )}
      <figcaption>{caption}</figcaption>
    </figure>
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
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : L("ບໍ່ສາມາດໂຫຼດຫຼັກຖານໄດ້.", "Could not load evidence.")))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const frames = data?.frames ?? [];

  return (
    <div className="evidence-backdrop" role="dialog" aria-modal="true" aria-label={L("ຫຼັກຖານການຜ່ານແດນ", "Crossing evidence")}>
      <div className="evidence-panel">
        <header className="evidence-head">
          <div>
            <p className="admin-eyebrow">{L("ຫຼັກຖານການຜ່ານແດນ", "Crossing evidence")}</p>
            <h3>
              <code className="admin-hash">{sessionId.slice(0, 8)}…</code>
            </h3>
          </div>
          <button className="icon-button" type="button" onClick={onClose} aria-label={L("ປິດ", "Close evidence")}>
            <X size={20} />
          </button>
        </header>

        {loading && <p className="admin-muted">{L("ກຳລັງໂຫຼດຫຼັກຖານ…", "Loading evidence…")}</p>}
        {error && <p className="form-error">{error}</p>}

        {!loading && !error && (
          <div className="evidence-body">
            {frames.length === 0 && (
              <p className="admin-muted">
{L("ບໍ່ມີຮູບທີ່ເກັບໄວ້ສຳລັບລາຍການນີ້. ການເກັບຫຼັກຖານເປີດໃຊ້ຕາມການຕັ້ງຄ່າລະບົບ (LALIGENCE_EVIDENCE_ENABLED).", "No frames retained for this session. Evidence capture is enabled per deployment (LALIGENCE_EVIDENCE_ENABLED).")}
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
                            {frame.encrypted && <span title={L("ເຂົ້າລະຫັດໄວ້", "Encrypted at rest")}> · 🔒</span>}
                          </figcaption>
                        </figure>
                      ) : (
                        <figure key={frame.id}>
                          <div className="evidence-thumb evidence-thumb-missing">{L("ໝົດອາຍຸ", "expired")}</div>
                          <figcaption>{L("ລຶບໄຟລ໌ແລ້ວ", "media disposed")}</figcaption>
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
                  {L("ລຳດັບການດຳເນີນການ", "Action timeline")} <span className="admin-muted">({localTimeZoneLabel})</span>
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
                        <span className={`attempt-badge attempt-badge-${event.outcome}`}>{statusLabel(event.outcome)}</span>
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
                {L("ປະຫວັດການເຂົ້າເບິ່ງ", "Access history")}{" "}
                <span className="admin-muted">
                  {L("(ຜູ້ທີ່ເຂົ້າເບິ່ງຂໍ້ມູນຜູ້ເດີນທາງນີ້ · ", "(who viewed this traveller · ")}{localTimeZoneLabel})
                </span>
              </h4>
              {(data?.access_log.length ?? 0) === 0 ? (
                <p className="admin-muted">{L("ຍັງບໍ່ມີການເຂົ້າເບິ່ງ.", "No prior access recorded.")}</p>
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

  const [watchlistHits, setWatchlistHits] = useState<WatchlistHit[]>([]);
  const [watchlistSummary, setWatchlistSummary] = useState<WatchlistSummary | null>(null);
  const [watchlistStatusFilter, setWatchlistStatusFilter] = useState("pending");
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [watchlistSubjectList, setWatchlistSubjectList] = useState<WatchlistSubject[]>([]);
  const [enrolName, setEnrolName] = useState("");
  const [enrolFile, setEnrolFile] = useState<File | null>(null);
  const [enrolBusy, setEnrolBusy] = useState(false);
  const [enrolMessage, setEnrolMessage] = useState<Status>(null);

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
        signOut(L("ໝົດເວລາເຂົ້າສູ່ລະບົບ. ກະລຸນາເຂົ້າສູ່ລະບົບໃໝ່.", "Session expired. Please sign in again."));
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
      handleAuthError(error, L("ໂຫຼດພາບລວມບໍ່ສຳເລັດ.", "Failed to load overview."));
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
      handleAuthError(error, L("ໂຫຼດ Face ID ບໍ່ສຳເລັດ.", "Failed to load Face IDs."));
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
        handleAuthError(error, L("ໂຫຼດລາຍການບໍ່ສຳເລັດ.", "Failed to load attempts."));
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

  const loadWatchlist = useCallback(async (status: string) => {
    setLoadingWatchlist(true);
    try {
      const [summary, hits, subjects] = await Promise.all([
        api.watchlistSummary(),
        api.watchlistHits(status || undefined),
        api.watchlistSubjects()
      ]);
      setWatchlistSummary(summary);
      setWatchlistHits(hits.hits);
      setWatchlistSubjectList(subjects.subjects);
    } catch (error) {
      handleAuthError(error, L("ໂຫຼດການແຈ້ງເຕືອນບໍ່ສຳເລັດ.", "Failed to load watchlist alerts."));
    } finally {
      setLoadingWatchlist(false);
    }
  }, []);

  const removeSubject = useCallback(
    async (subjectId: string, name: string) => {
      if (!window.confirm(L(`ລຶບ ${name} ອອກຈາກບັນຊີເຝົ້າລະວັງບໍ? ຮູບຂອງບຸກຄົນນີ້ຈະຖືກລຶບນຳ.`, `Remove ${name} from the watchlist? This deletes their photo.`))) return;
      try {
        await api.removeWatchlistSubject(subjectId);
        await loadWatchlist(watchlistStatusFilter);
      } catch (error) {
        handleAuthError(error, L("ບໍ່ສາມາດລຶບບຸກຄົນນີ້ໄດ້.", "Could not remove the person."));
      }
    },
    [loadWatchlist, watchlistStatusFilter]
  );

  const adjudicate = useCallback(
    async (hitId: string, status: "confirmed" | "dismissed") => {
      try {
        await api.adjudicateWatchlistHit(hitId, status);
        await loadWatchlist(watchlistStatusFilter);
      } catch (error) {
        handleAuthError(error, L("ບໍ່ສາມາດບັນທຶກການຕັດສິນໄດ້.", "Could not record the decision."));
      }
    },
    [loadWatchlist, watchlistStatusFilter]
  );

  const enrolFace = useCallback(
    async (event: FormEvent) => {
      event.preventDefault();
      if (!enrolFile || !enrolName.trim()) {
        setEnrolMessage({ kind: "error", message: L("ກະລຸນາປ້ອນຊື່ ແລະ ເລືອກຮູບໃບໜ້າ.", "Enter a name and choose a face photo.") });
        return;
      }
      setEnrolBusy(true);
      setEnrolMessage(null);
      try {
        const subject = await api.addWatchlistFace(enrolName.trim(), enrolFile);
        setEnrolMessage({ kind: "success", message: L(`ເພີ່ມ ${subject.full_name} ເຂົ້າບັນຊີເຝົ້າລະວັງແລ້ວ.`, `Added ${subject.full_name} to the watchlist.`) });
        setEnrolName("");
        setEnrolFile(null);
        await loadWatchlist(watchlistStatusFilter);
      } catch (error) {
        setEnrolMessage({
          kind: "error",
          message: error instanceof Error ? error.message : L("ບໍ່ສາມາດເພີ່ມບຸກຄົນນີ້ໄດ້.", "Could not add the person.")
        });
      } finally {
        setEnrolBusy(false);
      }
    },
    [enrolFile, enrolName, loadWatchlist, watchlistStatusFilter]
  );

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
    void loadWatchlist(watchlistStatusFilter);
    // Only re-run when the signed-in user changes; filters/pagination are
    // handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  useEffect(() => {
    if (!user) return;
    void loadWatchlist(watchlistStatusFilter);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watchlistStatusFilter]);

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
        message: error instanceof Error ? error.message : L("ເຂົ້າສູ່ລະບົບບໍ່ສຳເລັດ.", "Sign in failed.")
      });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteProfile = async (profile: UserProfile) => {
    if (!window.confirm(L(`ລຶບໂປຣໄຟລ໌ "${profile.user_id}" ຖາວອນບໍ? ບໍ່ສາມາດກູ້ຄືນໄດ້.`, `Permanently delete the profile for "${profile.user_id}"? This cannot be undone.`))) {
      return;
    }
    try {
      await api.deleteProfile(profile.user_id);
      setStatus({ kind: "success", message: L(`ລຶບໂປຣໄຟລ໌ ${profile.user_id} ແລ້ວ.`, `Deleted profile for ${profile.user_id}.`) });
      await Promise.all([loadProfiles(), loadOverview(), loadAudit()]);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : L(L("ລຶບບໍ່ສຳເລັດ.", "Purge failed."), "Delete failed.") });
    }
  };

  const handlePurgeProfiles = async () => {
    if (!window.confirm(L("ລຶບ Face ID ທັງໝົດທີ່ເກີນໄລຍະເກັບຮັກສາ (LALIGENCE_PROFILE_RETENTION_DAYS) ບໍ?", "Purge all Face IDs past the retention window (LALIGENCE_PROFILE_RETENTION_DAYS)?"))) {
      return;
    }
    try {
      const res = await api.purgeExpiredProfiles();
      setStatus({
        kind: "success",
        message: res.deleted_count
          ? L(`ລຶບ Face ID ທີ່ໝົດອາຍຸແລ້ວ ${res.deleted_count} ລາຍການ.`, `Purged ${res.deleted_count} expired Face ID(s).`)
          : L("ບໍ່ມີ Face ID ທີ່ເກີນໄລຍະເກັບຮັກສາ (ຫຼື ປິດການກຳນົດໄລຍະເກັບຮັກສາ).", "No Face IDs were past the retention window (or retention is disabled).")
      });
      await Promise.all([loadProfiles(), loadOverview(), loadAudit()]);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : L(L("ລຶບບໍ່ສຳເລັດ.", "Purge failed."), "Delete failed.") });
    }
  };

  const handlePurgeAttempts = async () => {
    if (!window.confirm(L("ລຶບລາຍການທັງໝົດທີ່ເກີນໄລຍະເກັບຮັກສາ (LALIGENCE_ATTEMPT_RETENTION_DAYS) ບໍ?", "Purge all attempts past the retention window (LALIGENCE_ATTEMPT_RETENTION_DAYS)?"))) {
      return;
    }
    try {
      const res = await api.purgeExpiredAttempts();
      setStatus({
        kind: "success",
        message: res.deleted_count
          ? L(`ລຶບລາຍການທີ່ໝົດອາຍຸແລ້ວ ${res.deleted_count} ລາຍການ.`, `Purged ${res.deleted_count} expired attempt(s).`)
          : L("ບໍ່ມີລາຍການທີ່ເກີນໄລຍະເກັບຮັກສາ (ຫຼື ປິດການກຳນົດໄລຍະເກັບຮັກສາ).", "No attempts were past the retention window (or retention is disabled).")
      });
      await Promise.all([loadAttempts(0), loadOverview()]);
    } catch (error) {
      setStatus({ kind: "error", message: error instanceof Error ? error.message : L(L("ລຶບບໍ່ສຳເລັດ.", "Purge failed."), "Delete failed.") });
    }
  };

  if (booting) {
    return (
      <main className="admin-shell">
        <p className="admin-muted">{L("ກຳລັງໂຫຼດ…", "Loading…")}</p>
      </main>
    );
  }

  // --- Login screen ----------------------------------------------------------
  if (!user) {
    return (
      <main className="admin-shell">
        <form className="admin-card admin-login" onSubmit={handleLogin}>
          <div className="admin-login-head"><span className="kyron-wordmark admin-logo"><KyronWordmark /></span><LanguageSwitch /></div>
          <h1 className="admin-title">
            <LockKeyhole size={18} />{L(" ເຂົ້າສູ່ລະບົບເຈົ້າໜ້າທີ່", " Staff sign in")}
          </h1>
          <p className="admin-muted">{L("ສຳລັບເຈົ້າໜ້າທີ່ເຂົ້າເຖິງລະບົບຈັດການການຢັ້ງຢືນ.", "Operator access to the verification console.")}</p>

          <label className="admin-field">
            <span>{L("ຊື່ຜູ້ໃຊ້", "Username")}</span>
            <input
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </label>
          <label className="admin-field">
            <span>{L("ລະຫັດຜ່ານ", "Password")}</span>
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
            {submitting ? L("ກຳລັງເຂົ້າສູ່ລະບົບ…", "Signing in…") : L("ເຂົ້າສູ່ລະບົບ", "Sign in")}
          </button>
          <a className="admin-back" href="#">{L("← ກັບໄປໜ້າຢັ້ງຢືນ", "← Back to verification")}</a>
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
          <span className="admin-logo-sm" aria-label="Kyron"><KyronMark size={28} /></span>
          <div>
            <strong>{L("ລະບົບຜູ້ດູແລ", "Admin portal")}</strong>
            <span className="admin-muted">
              <ShieldCheck size={13} /> {user.username} · {statusLabel(user.role)}
            </span>
          </div>
        </div>
        <div className="admin-actions">
          <LanguageSwitch />
          <button className="admin-ghost" onClick={() => signOut()}>
            <LogOut size={15} />{L(" ອອກຈາກລະບົບ", " Sign out")}
          </button>
        </div>
      </header>

      <nav className="admin-tabs" role="tablist">
        <button
          role="tab"
          className={`admin-tab ${tab === "overview" ? "active" : ""}`}
          onClick={() => setTab("overview")}
        >
          <LayoutDashboard size={15} />{L(" ພາບລວມ", " Overview")}
        </button>
        <button
          role="tab"
          className={`admin-tab ${tab === "attempts" ? "active" : ""}`}
          onClick={() => setTab("attempts")}
        >
          <ListChecks size={15} />{L(" ລາຍການ eKYC", " Attempts")}
          {attemptsTotal > 0 && <span className="admin-tab-count">{attemptsTotal}</span>}
        </button>
        <button
          role="tab"
          className={`admin-tab ${tab === "watchlist" ? "active" : ""}`}
          onClick={() => setTab("watchlist")}
        >
          <ShieldAlert size={15} />{L(" ບັນຊີເຝົ້າລະວັງ", " Watchlist")}
          {watchlistSummary && watchlistSummary.pending_hits > 0 && (
            <span className="admin-tab-count admin-tab-count-alert">{watchlistSummary.pending_hits}</span>
          )}
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
          <ScrollText size={15} />{L(" ບັນທຶກການກວດສອບ", " Audit Log")}
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
            <h2>{L("ພາບລວມ", "Overview")}</h2>
            <button className="admin-ghost" onClick={() => void loadOverview()} disabled={loadingOverview}>
              <RefreshCw size={14} />{L(" ໂຫຼດຄືນ", " Refresh")}
            </button>
          </div>

          {loadingOverview && !overview ? (
            <p className="admin-muted">{L("ກຳລັງໂຫຼດພາບລວມ…", "Loading overview…")}</p>
          ) : overview ? (
            <>
              <div className="admin-stat-grid">
                <div className="admin-stat-card">
                  <span className="admin-stat-label">{L("ລາຍການ eKYC ທັງໝົດ", "Total eKYC attempts")}</span>
                  <span className="admin-stat-value">{overview.attempts.total}</span>
                  <div className="admin-stat-breakdown">
                    <span className="attempt-badge attempt-badge-passed">{L("ຜ່ານ ", "")}{overview.attempts.passed}{L("", " passed")}</span>
                    <span className="attempt-badge attempt-badge-pending">{L("ລໍຖ້າ ", "")}{overview.attempts.pending}{L("", " pending")}</span>
                    <span className="attempt-badge attempt-badge-rejected">{L("ບໍ່ຜ່ານ ", "")}{overview.attempts.rejected}{L("", " rejected")}</span>
                  </div>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-label">{L("Face ID ທີ່ລົງທະບຽນ", "Enrolled Face IDs")}</span>
                  <span className="admin-stat-value">{overview.enrolled_face_ids}</span>
                  <span className="admin-muted">{L("ໄລຍະເກັບຮັກສາ", "Retention")}: {overview.profile_retention_days > 0 ? L(`${overview.profile_retention_days} ມື້`, `${overview.profile_retention_days} days`) : L("ບໍ່ກຳນົດ", "indefinite")}</span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-label">{L("ຄວາມຖືກຕ້ອງຂອງບັນທຶກ", "Audit log integrity")}</span>
                  <span className={`admin-integrity ${overview.audit_chain_ok ? "ok" : "broken"}`} style={{ marginTop: 4 }}>
                    {overview.audit_chain_ok ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
                    {overview.audit_log_enabled
                      ? overview.audit_chain_ok
                        ? L(`ກວດແລ້ວ · ${overview.audit_entries} ລາຍການ`, `Verified · ${overview.audit_entries} entries`)
                        : L("ກວດພົບການແກ້ໄຂ", "Tampering detected")
                      : L("ປິດໃຊ້ງານ", "Disabled")}
                  </span>
                </div>
                <div className="admin-stat-card">
                  <span className="admin-stat-label">{L("ໄລຍະເກັບລາຍການ", "Attempt log retention")}</span>
                  <span className="admin-stat-value">
                    {overview.attempt_retention_days > 0 ? L(`${overview.attempt_retention_days} ມື້`, `${overview.attempt_retention_days}d`) : "∞"}
                  </span>
                  <span className="admin-muted">LALIGENCE_ATTEMPT_RETENTION_DAYS</span>
                </div>
              </div>
              <p className="admin-muted admin-overview-hint">
{L("ທຸກລາຍການ eKYC ຖືກບັນທຶກອັດຕະໂນມັດ (ຜົນການຕັດສິນ, ຜົນແຕ່ລະຂັ້ນຕອນ, ບໍ່ເກັບຮູບ ຫຼື ຂໍ້ມູນຊີວະມິຕິ). ເບິ່ງແຖບ \"ລາຍການ eKYC\" ສຳລັບລາຍການທັງໝົດ ແລະ \"Face ID\" ສຳລັບຜູ້ທີ່ລົງທະບຽນ.", "Every eKYC attempt is recorded automatically (decision, per-step results, no raw images or biometrics). See the Attempts tab for the full list, and Face IDs for who has enrolled.")}
              </p>
            </>
          ) : (
            <p className="admin-muted">{L("ຍັງບໍ່ມີຂໍ້ມູນ.", "No data yet.")}</p>
          )}
        </section>
      )}

      {tab === "attempts" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>
{L("ລາຍການ eKYC", "eKYC Attempts")}<span className="admin-count">{attemptsTotal}</span>
            </h2>
            <div className="admin-actions">
              <button className="admin-ghost" onClick={() => void loadAttempts()} disabled={loadingAttempts}>
                <RefreshCw size={14} />{L(" ໂຫຼດຄືນ", " Refresh")}
              </button>
              <button className="admin-ghost admin-danger" onClick={handlePurgeAttempts}>
{L("ລຶບລາຍການໝົດອາຍຸ", "Purge expired")}
              </button>
            </div>
          </div>

          <div className="admin-filters">
            <select
              className="admin-select"
              value={decisionFilter}
              onChange={(e) => setDecisionFilter(e.target.value)}
              aria-label={L("ກັ່ນຕອງຕາມຜົນ", "Filter by decision")}
            >
              <option value="">{L("ທຸກຜົນ", "All decisions")}</option>
              <option value="passed">{L("ຜ່ານ", "Passed")}</option>
              <option value="pending">{L("ລໍຖ້າ", "Pending")}</option>
              <option value="rejected">{L("ບໍ່ຜ່ານ", "Rejected")}</option>
            </select>
            <label className="admin-search">
              <Search size={14} />
              <input
                type="text"
                placeholder={L("ກັ່ນຕອງຕາມລະຫັດຜູ້ໃຊ້", "Filter by user ID")}
                value={userFilter}
                onChange={(e) => setUserFilter(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && applyAttemptFilters()}
              />
            </label>
            <button className="admin-ghost" onClick={applyAttemptFilters}>
{L("ນຳໃຊ້", "Apply")}
            </button>
          </div>

          {loadingAttempts ? (
            <p className="admin-muted">{L("ກຳລັງໂຫຼດລາຍການ…", "Loading attempts…")}</p>
          ) : attempts.length === 0 ? (
            <p className="admin-muted">{L("ຍັງບໍ່ມີລາຍການ eKYC.", "No eKYC attempts recorded yet.")}</p>
          ) : (
            <>
              <div className="admin-table-wrap">
                <table className="admin-table">
                  <thead>
                    <tr>
                      <th>{L("ລາຍການ", "Session")}</th>
                      <th>{L("ຜູ້ໃຊ້", "User")}</th>
                      <th>{L("ຜົນ", "Decision")}</th>
                      <th>{L("ເອກະສານ", "Document")}</th>
                      <th>{L("ຂັ້ນຕອນ", "Steps")}</th>
                      <th>{L("ທຽບໃບໜ້າ", "Face match")}</th>
                      <th>{L("IP", "Client IP")}</th>
                      <th>{L("ອັບເດດ", "Updated")}</th>
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
                            title={L("ເບິ່ງຫຼັກຖານຂອງລາຍການນີ້", "View retained evidence for this crossing")}
                          >
                            <Images size={13} />
                            <code className="admin-hash">{a.session_id.slice(0, 8)}…</code>
                          </button>
                        </td>
                        <td>{a.user_id}</td>
                        <td>
                          <span className={`attempt-badge attempt-badge-${a.decision}`} title={a.reason_codes.join(", ") || undefined}>
                            {statusLabel(a.decision)}
                          </span>
                        </td>
                        <td>
                          {statusLabel(a.document_type)}
                          {a.document_status && <span className="admin-muted"> ({statusLabel(a.document_status)})</span>}
                        </td>
                        <td>
                          <span
                            className={`admin-step-dot ${a.active_liveness_passed ? "on" : ""}`}
                            title={L("ກວດໃບໜ້າຈິງ", "Active liveness")}
                          >
                            AL
                          </span>
                          <span className={`admin-step-dot ${a.hand_challenge_passed ? "on" : ""}`} title={L("ທ່າທາງມື", "Hand gesture")}>
                            HG
                          </span>
                          <span
                            className={`admin-step-dot ${a.passive_liveness_passed ? "on" : ""}`}
                            title={L("ເຊວຟີ / ໃບໜ້າຈິງ", "Passive liveness")}
                          >
                            PL
                          </span>
                          <span className={`admin-step-dot ${a.contact_confirmed ? "on" : ""}`} title={L("ຢືນຢັນການຕິດຕໍ່", "Contact confirmed")}>
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
                  <ChevronLeft size={14} />{L(" ກ່ອນໜ້າ", " Prev")}
                </button>
                <span className="admin-muted">
                  {L("ໜ້າ ", "Page ")}{page}{L(" / ", " of ")}{pageCount}
                </span>
                <button
                  className="admin-ghost"
                  disabled={attemptOffset + ATTEMPT_PAGE_SIZE >= attemptsTotal}
                  onClick={() => setAttemptOffset(attemptOffset + ATTEMPT_PAGE_SIZE)}
                >
                  {L("ຖັດໄປ ", "Next ")}<ChevronRight size={14} />
                </button>
              </div>
            </>
          )}
        </section>
      )}

      {tab === "watchlist" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>{L("ການແຈ້ງເຕືອນບັນຊີເຝົ້າລະວັງ", "Watchlist alerts")}</h2>
            <div className="admin-filters">
              <select
                className="admin-select"
                value={watchlistStatusFilter}
                onChange={(event) => setWatchlistStatusFilter(event.target.value)}
              >
                <option value="pending">{L("ລໍຖ້າ", "Pending")}</option>
                <option value="confirmed">{L("ຢືນຢັນແລ້ວ", "Confirmed")}</option>
                <option value="dismissed">{L("ປັດຕົກ", "Dismissed")}</option>
                <option value="">{L("ທັງໝົດ", "All")}</option>
              </select>
              <button
                className="admin-ghost"
                onClick={() => void loadWatchlist(watchlistStatusFilter)}
                disabled={loadingWatchlist}
              >
                <RefreshCw size={15} />{L(" ໂຫຼດຄືນ", " Refresh")}
              </button>
            </div>
          </div>

          {watchlistSummary && !watchlistSummary.enabled && (
            <p className="admin-note admin-note-warn">
{L("ການກວດບັນຊີເຝົ້າລະວັງ", "Watchlist screening is")}<strong>{L("ປິດຢູ່", "disabled")}</strong>{L(". ຕັ້ງຄ່າ", ". Set")}
              <code> LALIGENCE_WATCHLIST_ENABLED=true</code>{L(" ແລະ ນຳເຂົ້າລາຍຊື່ເພື່ອເປີດໃຊ້.", " and import a list to activate it.")}
            </p>
          )}
          {watchlistSummary && watchlistSummary.enabled && (
            <p className="admin-note">
              {L("ມີ ", "")}{watchlistSummary.active_subject_count.toLocaleString()}{L(" ຄົນໃນລາຍຊື່ ·", " active on the list ·")}{" "}
              {L("ລໍຖ້າ ", "")}{watchlistSummary.pending_hits.toLocaleString()}{L(" ·", " pending ·")}{" "}
              {L("ແຈ້ງເຕືອນທັງໝົດ ", "")}{watchlistSummary.total_hits.toLocaleString()}{L("", " total alerts")}
            </p>
          )}

          <form className="watchlist-enrol" onSubmit={enrolFace}>
            <span className="watchlist-enrol-title">{L("ເພີ່ມບຸກຄົນດ້ວຍຮູບໃບໜ້າ", "Add a person by face")}</span>
            <input
              className="watchlist-enrol-name"
              type="text"
              placeholder={L("ຊື່ ແລະ ນາມສະກຸນ", "Full name")}
              value={enrolName}
              onChange={(event) => setEnrolName(event.target.value)}
              disabled={enrolBusy}
            />
            <input
              className="watchlist-enrol-file"
              type="file"
              accept="image/*"
              onChange={(event) => setEnrolFile(event.target.files?.[0] ?? null)}
              disabled={enrolBusy}
            />
            <button className="watchlist-confirm" type="submit" disabled={enrolBusy}>
              {enrolBusy ? L("ກຳລັງເພີ່ມ…", "Adding…") : L("ເພີ່ມເຂົ້າບັນຊີ", "Add to watchlist")}
            </button>
            {enrolMessage && (
              <span className={`watchlist-enrol-msg watchlist-enrol-${enrolMessage.kind}`}>
                {enrolMessage.message}
              </span>
            )}
          </form>

          {watchlistSubjectList.length > 0 && (
            <div className="watchlist-subjects">
              <p className="watchlist-subjects-title">{L("ບຸກຄົນໃນບັນຊີເຝົ້າລະວັງ (", "People on the watchlist (")}{watchlistSubjectList.length})</p>
              <div className="watchlist-subject-list">
                {watchlistSubjectList.map((subject) => (
                  <div className="watchlist-subject" key={subject.id}>
                    {subject.has_face ? (
                      <WatchlistPhoto
                        fetcher={() => api.watchlistSubjectPhotoUrl(subject.id)}
                        caption=""
                      />
                    ) : (
                      <div className="watchlist-photo-box watchlist-photo-missing">{L("ບໍ່ມີຮູບ", "no photo")}</div>
                    )}
                    <div className="watchlist-subject-info">
                      <span className="watchlist-subject-name">{subject.full_name}</span>
                      <span className="watchlist-subject-meta">
                        {[
                          subject.has_face ? L("ມີຮູບໃບໜ້າ", "face") : null,
                          subject.passport_numbers.length ? subject.passport_numbers.join(", ") : null,
                          subject.date_of_birth,
                          subject.reason
                        ]
                          .filter(Boolean)
                          .join(" · ") || "—"}
                      </span>
                    </div>
                    <button
                      className="watchlist-remove"
                      onClick={() => void removeSubject(subject.id, subject.full_name)}
                    >
                      <Trash2 size={14} />{L(" ລຶບ", " Remove")}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {watchlistHits.length === 0 ? (
            <p className="admin-empty">
              {loadingWatchlist ? L("ກຳລັງໂຫຼດ…", "Loading…") : L("ບໍ່ມີການແຈ້ງເຕືອນ.", "No alerts for this filter.")}
            </p>
          ) : (
            <div className="watchlist-list">
              {watchlistHits.map((hit) => (
                <article className={`watchlist-hit watchlist-hit-${hit.status}`} key={hit.id}>
                  <div className="watchlist-hit-main">
                    <div className="watchlist-hit-head">
                      <ShieldAlert size={18} />
                      <span className="watchlist-hit-name">{hit.subject_name}</span>
                      <span className={`watchlist-status watchlist-status-${hit.status}`}>{statusLabel(hit.status)}</span>
                    </div>
                    <p className="watchlist-hit-meta">
                      {L("ກົງກັນດ້ວຍ ", "Matched on ")}<strong>{hit.matched_on.replace(/_/g, " + ")}</strong> ·{" "}
                      {L("ຄວາມໝັ້ນໃຈ ", "")}{Math.round(hit.confidence * 100)}{L("%", "% confidence")}
                      {hit.reason ? <> · {hit.reason}</> : null}
                    </p>
                    {hit.matched_on === "face" && (
                      <div className="watchlist-faces">
                        {hit.has_probe && (
                          <WatchlistPhoto
                            fetcher={() => api.watchlistHitProbeUrl(hit.id)}
                            caption={L("ໃບໜ້າທີ່ອັບໂຫຼດ", "Uploaded face")}
                          />
                        )}
                        <WatchlistPhoto
                          fetcher={() => api.watchlistSubjectPhotoUrl(hit.subject_id)}
                          caption={L("ຮູບໃນບັນຊີ", "Watchlist photo")}
                        />
                      </div>
                    )}
                    <p className="watchlist-hit-sub">
                      <button
                        className="admin-linkish"
                        onClick={() => {
                          setEvidenceSession(hit.session_id);
                        }}
                      >
                        {L("ລາຍການ ", "Session ")}{hit.session_id.slice(0, 8)}
                      </button>
                      {hit.user_id ? <> · {hit.user_id}</> : null}
                      {hit.created_at ? <> · {formatLocalDateTime(hit.created_at)}</> : null}
                    </p>
                    {hit.adjudicated_by && (
                      <p className="watchlist-hit-sub">
                        {statusLabel(hit.status)} {L("ໂດຍ", "by")} {hit.adjudicated_by}
                        {hit.adjudicated_at ? ` · ${formatLocalDateTime(hit.adjudicated_at)}` : ""}
                      </p>
                    )}
                  </div>
                  {hit.status === "pending" && (
                    <div className="watchlist-hit-actions">
                      <button
                        className="watchlist-confirm"
                        onClick={() => void adjudicate(hit.id, "confirmed")}
                      >
{L("ຢືນຢັນວ່າກົງກັນ", "Confirm match")}
                      </button>
                      <button
                        className="watchlist-dismiss"
                        onClick={() => void adjudicate(hit.id, "dismissed")}
                      >
{L("ປັດຕົກ", "Dismiss")}
                      </button>
                    </div>
                  )}
                </article>
              ))}
            </div>
          )}
        </section>
      )}

      {tab === "faceids" && (
        <section className="admin-card">
          <div className="admin-section-head">
            <h2>
{L("Face ID ທີ່ລົງທະບຽນ", "Enrolled Face IDs")}<span className="admin-count">{profiles.length}</span>
            </h2>
            <div className="admin-actions">
              <button className="admin-ghost" onClick={() => void loadProfiles()} disabled={loadingProfiles}>
                <RefreshCw size={14} />{L(" ໂຫຼດຄືນ", " Refresh")}
              </button>
              <button className="admin-ghost admin-danger" onClick={handlePurgeProfiles}>
{L("ລຶບລາຍການໝົດອາຍຸ", "Purge expired")}
              </button>
            </div>
          </div>

          {loadingProfiles ? (
            <p className="admin-muted">{L("ກຳລັງໂຫຼດ Face ID…", "Loading Face IDs…")}</p>
          ) : profiles.length === 0 ? (
            <p className="admin-muted">{L("ຍັງບໍ່ມີ Face ID ທີ່ລົງທະບຽນ.", "No enrolled Face IDs.")}</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>Face ID</th>
                    <th>{L("ຜູ້ໃຊ້", "User")}</th>
                    <th>{L("ຊື່", "Name")}</th>
                    <th>{L("ສັນຊາດ", "Nationality")}</th>
                    <th>{L("ລົງທະບຽນ", "Enrolled")}</th>
                    <th>{L("ເຂົ້າລະບົບລ່າສຸດ", "Last login")}</th>
                    <th>{L("ການຍິນຍອມ", "Consent")}</th>
                    <th aria-label={L("ການດຳເນີນການ", "Actions")} />
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
                        <button className="admin-icon-danger" onClick={() => handleDeleteProfile(p)} title={L("ລຶບ Face ID ນີ້", "Delete this Face ID")}>
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
{L("ບັນທຶກການກວດສອບ", "Audit log")}
            </h2>
            <div className="admin-actions">
              {auditVerify && (
                <span className={`admin-integrity ${auditVerify.ok ? "ok" : "broken"}`}>
                  {auditVerify.ok ? <ShieldCheck size={14} /> : <ShieldAlert size={14} />}
                  {auditVerify.ok
                    ? L(`ກວດແລ້ວ · ${auditVerify.entries} ລາຍການ`, `Chain verified · ${auditVerify.entries} entries`)
                    : L(`ກວດພົບການແກ້ໄຂທີ່ #${auditVerify.broken_at}`, `Tampering detected at #${auditVerify.broken_at}`)}
                </span>
              )}
              <button className="admin-ghost" onClick={() => void loadAudit()}>
                <RefreshCw size={14} />{L(" ກວດຄືນ", " Re-verify")}
              </button>
            </div>
          </div>

          {audit.length === 0 ? (
            <p className="admin-muted">{L("ຍັງບໍ່ມີບັນທຶກ.", "No audit events yet.")}</p>
          ) : (
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>#</th>
                    <th>{L("ເວລາ", "Time")}</th>
                    <th>{L("ປະເພດ", "Type")}</th>
                    <th>{L("ການດຳເນີນການ", "Action")}</th>
                    <th>{L("ຜູ້ດຳເນີນການ", "Actor")}</th>
                    <th>{L("ເປົ້າໝາຍ", "Subject")}</th>
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
