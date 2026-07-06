const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, ImageRun,
  AlignmentType, LevelFormat, HeadingLevel, BorderStyle, WidthType, ShadingType,
  TableOfContents, PageNumber, PageBreak, Header, Footer, VerticalAlign,
} = require("docx");

const WORKFLOW_IMG = "/Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex/docs/system-workflow.png";

const OUT = "/Users/chilanhouthnitvongkhay/Downloads/ekyc-system-codex/docs/kyron-ekyc-white-paper-draft.docx";
const CW = 9360; // content width (US Letter, 1" margins)
const NAVY = "0B1B3A", GOLD = "C9A12A", MUTE = "5A6478", HEAD = "D5E1F5", ZEBRA = "F3F6FC";

// --- helpers ---------------------------------------------------------------
const H1 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)] });
const H2 = (t) => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const P = (t, opts = {}) => new Paragraph({ spacing: { after: 120, line: 276 }, children: parseRuns(t), ...opts });
const BULLET = (t) => new Paragraph({ numbering: { reference: "b", level: 0 }, spacing: { after: 60, line: 264 }, children: parseRuns(t) });
const NUM = (t) => new Paragraph({ numbering: { reference: "n", level: 0 }, spacing: { after: 60, line: 264 }, children: parseRuns(t) });

// tiny **bold** parser
function parseRuns(t) {
  const out = [];
  t.split(/(\*\*[^*]+\*\*)/).forEach((seg) => {
    if (!seg) return;
    if (seg.startsWith("**") && seg.endsWith("**")) out.push(new TextRun({ text: seg.slice(2, -2), bold: true }));
    else out.push(new TextRun(seg));
  });
  return out.length ? out : [new TextRun(t)];
}

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border,
  insideHorizontal: border, insideVertical: border };

function table(widths, rows, { headerFill = HEAD, zebra = true } = {}) {
  return new Table({
    width: { size: CW, type: WidthType.DXA },
    columnWidths: widths,
    borders,
    rows: rows.map((cells, ri) =>
      new TableRow({
        tableHeader: ri === 0,
        children: cells.map((c, ci) =>
          new TableCell({
            width: { size: widths[ci], type: WidthType.DXA },
            margins: { top: 70, bottom: 70, left: 110, right: 110 },
            verticalAlign: VerticalAlign.CENTER,
            shading: { fill: ri === 0 ? headerFill : (zebra && ri % 2 === 0 ? ZEBRA : "FFFFFF"), type: ShadingType.CLEAR },
            children: String(c).split("\n").map((line) =>
              new Paragraph({
                spacing: { after: 0, line: 252 },
                children: [new TextRun({ text: line, bold: ri === 0, color: ri === 0 ? NAVY : undefined, size: 19 })],
              })),
          })),
      })),
  });
}

// --- document --------------------------------------------------------------
const children = [];

// Title page
children.push(
  new Paragraph({ spacing: { before: 1800, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "KYRON eKYC", bold: true, size: 24, color: GOLD, characterSpacing: 60 })] }),
  new Paragraph({ spacing: { before: 240, after: 0 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "A Standards-Aligned Identity Verification Platform", bold: true, size: 48, color: NAVY })] }),
  new Paragraph({ spacing: { before: 200, after: 0 }, alignment: AlignmentType.CENTER,
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: GOLD, space: 8 } },
    children: [new TextRun({ text: "White Paper — Draft", size: 28, color: MUTE })] }),
  new Paragraph({ spacing: { before: 260 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Document-and-biometric identity proofing aligned toward NIST SP 800-63A IAL2,", italics: true, size: 22, color: MUTE })] }),
  new Paragraph({ spacing: { after: 600 }, alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "with production-grade security, privacy, and governance controls.", italics: true, size: 22, color: MUTE })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
    children: [new TextRun({ text: "Version 0.1 (Draft)  ·  2026-07-01", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 40 },
    children: [new TextRun({ text: "Prepared by: Kyron project team", size: 22 })] }),
  new Paragraph({ alignment: AlignmentType.CENTER,
    children: [new TextRun({ text: "Status: aligned toward IAL2 — not independently certified.", size: 20, italics: true, color: "B42318" })] }),
  new Paragraph({ children: [new PageBreak()] }),
);

// Contents (manual — always renders)
children.push(new Paragraph({ spacing: { after: 200 }, children: [new TextRun({ text: "Contents", bold: true, size: 32, color: NAVY })] }));
[
  "1.  Executive Summary",
  "2.  Introduction & Problem",
  "3.  System Overview",
  "4.  The Verification Workflow",
  "5.  Security Architecture",
  "6.  Privacy & Data Protection",
  "7.  Standards Alignment",
  "8.  Accuracy & Evaluation",
  "9.  Governance & Compliance",
  "10.  IAL2 Readiness",
  "11.  Roadmap to Certification",
  "12.  Limitations & Honest Status",
  "13.  Conclusion",
].forEach((t) => children.push(new Paragraph({ spacing: { after: 90 }, indent: { left: 240 },
  children: [new TextRun({ text: t, size: 22, color: "1A1A1A" })] })));
children.push(new Paragraph({ children: [new PageBreak()] }));

// 1. Executive summary
children.push(H1("1. Executive Summary"));
children.push(P("Kyron eKYC is a remote identity-verification platform that proofs a person from a government identity document and a live selfie, then lets them return by face (login and payment). It combines passport/ID document proofing, passive and active presentation-attack detection (liveness), a randomized gesture challenge, one-to-one biometric matching to the document portrait, and an explainable risk decision — in a single workflow designed to align with **NIST SP 800-63A Identity Assurance Level 2 (IAL2)**."));
children.push(P("This paper describes the system, its security and privacy architecture, the standards it targets, and — candidly — what has been achieved versus what remains before an IAL2 claim can be made. The engineering foundation is strong: every requirement satisfiable in software has been implemented and covered by an automated test suite (150+ tests). The remaining work is **not code** — it is a labelled dataset (to measure biometric accuracy at the required threshold), two external integrations, and independent laboratory assessment plus in-region hosting."));
children.push(P("**Honest status.** Kyron is aligned toward IAL2 and is assessment-preparing; it is **not** certified. No claim of NIST, ISO, bank-grade, or government certification should be made until an independent assessment is complete."));

// 2. Introduction
children.push(H1("2. Introduction & Problem"));
children.push(P("Remote onboarding must answer one question with high assurance: is this person who they claim to be? Attackers attempt this with printed photos, screen and video replays, deepfakes, and forged or tampered documents. Regulated use cases (financial onboarding, KYC/AML, government services) additionally require documented, auditable processes and strict protection of the most sensitive category of personal data — biometrics and identity documents."));
children.push(P("Kyron addresses this by binding a strong identity document to a verified live person, resisting presentation and replay attacks, and recording an explainable decision — while treating the underlying biometric and PII as special-category data throughout its lifecycle."));

// 3. System overview
children.push(H1("3. System Overview"));
children.push(P("Kyron is a web application with a Python (FastAPI) backend and a React/TypeScript (Vite) frontend. Machine-learning components are pretrained, open models run either in the browser or on the server:"));
children.push(BULLET("**Face detection & embedding:** YuNet (detection) and SFace (recognition) via ONNX Runtime, for the one-to-one document-to-selfie match."));
children.push(BULLET("**Passive anti-spoof (PAD):** a MiniFASNet-family model with burst-mode voting and screen/print/held-phone heuristics."));
children.push(BULLET("**Active liveness & gesture:** MediaPipe FaceMesh and Hands drive randomized head-action and finger-count challenges, with server-side verification of evidence bursts."));
children.push(BULLET("**Document OCR & fraud checks:** Tesseract/Surya OCR with passport TD3 MRZ parsing and check-digit validation, plus tamper and recapture (print/screen) analysis."));
children.push(P("Verified profiles (a protected face template plus minimal document attributes) are stored in a SQL profile store (SQLite for development, PostgreSQL for production). Raw document, selfie, and liveness images are analyzed in memory and never written to disk."));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { before: 160, after: 40 },
  children: [new ImageRun({ type: "png", data: fs.readFileSync(WORKFLOW_IMG),
    transformation: { width: 600, height: 424 },
    altText: { title: "Kyron eKYC system workflow", description: "End-to-end verification workflow: document proofing, liveness, gesture, face match, decision, enrollment.", name: "SystemWorkflow" } })] }));
children.push(new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 160 },
  children: [new TextRun({ text: "Figure 1. Kyron eKYC system workflow — from document capture through the risk decision and enrollment.", italics: true, size: 18, color: MUTE })] }));

// 4. Workflow
children.push(H1("4. The Verification Workflow"));
children.push(P("A verification session proceeds through explainable steps, each contributing to a final risk decision with machine-readable reason codes:"));
children.push(NUM("**Document proofing** — capture a passport or national ID; OCR the data; validate the MRZ (hard-fail on an invalid TD3 MRZ); screen for tampering and print/screen recapture."));
children.push(NUM("**Passive liveness (PAD)** — detect presentation attacks (printed photo, screen/video replay) from the selfie burst."));
children.push(NUM("**Active liveness** — a randomized head-action challenge verified from server-side evidence, not trusted from client landmarks."));
children.push(NUM("**Gesture challenge** — a randomized finger-count/hand-sign step, ordering-enforced and protected by one-time server-issued nonces to resist replay."));
children.push(NUM("**One-to-one face match** — compare the live selfie to the document portrait; score against a configurable threshold."));
children.push(NUM("**Risk decision** — aggregate all signals into passed / pending / rejected with reason codes; on pass, the user may enroll a protected template."));
children.push(P("Two returning-user flows reuse the enrolled template: **Face Login** (authenticate by face, with liveness and rate limiting) and **Face Pay** (a face-authorized transfer demo). An optional **contact-confirmation** step (enrollment code to a validated email/phone) and a **notification of proofing** implement IAL2 proofing steps 5–6 when enabled."));

// 5. Security
children.push(H1("5. Security Architecture"));
children.push(P("Security controls are implemented, configurable, and test-covered. Most are off by default so the public demo stays open, and enabled in production via environment configuration."));
children.push(table([3060, 6300], [
  ["Control", "Summary"],
  ["Encryption at rest", "Face templates and PII encrypted with authenticated symmetric encryption (Fernet); PII in an encrypted blob; passport number kept queryable via a keyed blind index."],
  ["Cancelable templates (ISO 24745)", "A key-derived orthonormal transform makes stored templates revocable/renewable by re-keying and unlinkable across systems — while preserving matching scores exactly."],
  ["Key management", "Every secret can be sourced from a manager (file:/command:/env: specs) rather than a bare variable; encryption and JWT keys support rotation (retired keys still decrypt/verify)."],
  ["Authentication & RBAC", "Optional API-key gate on all endpoints, plus per-user OAuth2 password → JWT with role-based access; admin endpoints fail closed."],
  ["Session security", "Verification sessions are unguessable, short-lived (idle + absolute TTL), and client-bound by a per-session token to prevent id-only hijack/replay."],
  ["Audit logging", "Tamper-evident, hash-chained trail of authentication, PII access, admin actions, and enrollment; an integrity-verify endpoint detects any edit or deletion."],
  ["Abuse & transport", "Per-client and global rate limits (with a dedicated face-login throttle), an explicit CORS allowlist, and HTTPS/HSTS in hosted deployments."],
  ["Supply chain", "CI dependency scanning (pip-audit + npm audit) on every change, with Dependabot; the initial scan found and cleared 21 advisories."],
]));

// 6. Privacy
children.push(H1("6. Privacy & Data Protection"));
children.push(P("Kyron treats biometrics and document PII as special-category data and applies data-protection-by-design:"));
children.push(BULLET("**Data minimization** — no raw biometric media is stored; only a protected template and minimal attributes persist, and only on enrollment. Embeddings are never exposed through API responses."));
children.push(BULLET("**Consent** — a versioned consent notice and opt-in gate; each enrolled profile records the consent terms version and timestamp."));
children.push(BULLET("**Retention** — a configurable retention window with an administrative auto-purge of profiles idle beyond it."));
children.push(BULLET("**Data-subject rights** — self-service export (portability) and erasure, authenticated by the user's own live selfie; administrative deletion is also available and audited."));
children.push(P("These map to GDPR Articles 5, 9, 13, 17, 30 and 32, and are supported by the tamper-evident audit log for accountability."));

// 7. Standards
children.push(H1("7. Standards Alignment"));
children.push(P("Kyron is designed and documented against the following standards. Alignment is self-assessed and evidence-backed; it is not a certification."));
children.push(table([2760, 3900, 2700], [
  ["Standard", "Relevance", "Status"],
  ["NIST SP 800-63A (IAL2)", "Remote identity proofing", "Aligned (partial); assessment pending"],
  ["NIST SP 800-63B", "Biometric authenticator (face login)", "Aligned (partial)"],
  ["ISO/IEC 30107-3", "Presentation-attack detection testing", "Built to; independent test pending"],
  ["ISO/IEC 24745", "Biometric template protection", "Implemented (cancelable templates)"],
  ["ISO/IEC 27001", "Information-security management", "Controls + draft ISMS in place"],
  ["ICAO Doc 9303", "Machine-readable passports (MRZ)", "TD3 MRZ parse + check digits"],
  ["GDPR / local law", "Special-category data protection", "By-design; legal review pending"],
  ["FATF", "AML/KYC customer due diligence", "Supports CDD + record-keeping"],
]));
children.push(P("A clause-by-clause control-to-evidence mapping is maintained separately (docs/controls-standards-mapping.md)."));

// 8. Accuracy
children.push(H1("8. Accuracy & Evaluation"));
children.push(P("Honesty about measurement is a design principle. Attack detection has been exercised against internal print and phone-screen replay sets, and one-to-one face matching has an initial benchmark on the public LFW dataset (~1% equal-error rate). However, this is **not** the operational task or the IAL2 threshold:"));
children.push(BULLET("The **operational** metric — false-match / false-non-match rate on **genuine document-to-selfie pairs**, at the IAL2 bar (false-match rate ≤ 1:10,000) — has not yet been measured, because it requires a labelled, consented dataset of real pairs."));
children.push(BULLET("Presentation-attack detection has not been evaluated by an accredited laboratory (ISO/IEC 30107-3 APCER/BPCER), which is required before any formal accuracy claim."));
children.push(P("Evaluation harnesses (face matching, active liveness, document print/copy) and a detailed data-collection plan are in place, so measurement can begin as soon as suitable data is available. No accuracy figure in this paper should be read as a certified or production number."));

// 9. Governance
children.push(H1("9. Governance & Compliance"));
children.push(P("A draft Information Security Management System (ISMS) documentation set accompanies the technical controls, each grounded in the system as built so the documents double as evidence:"));
children.push(BULLET("**Data Protection & Retention Policy** — lawful basis, data categories, security measures, retention schedule, and data-subject rights."));
children.push(BULLET("**Data Protection Impact Assessment (DPIA)** — a risk register for the biometric processing with mitigations and residual ratings."));
children.push(BULLET("**Incident Response Plan** — severity tiers, response phases, breach-notification timelines, and a key-compromise runbook."));
children.push(BULLET("**Internal Gap Assessment & Statement of Applicability** — a self-audit against ISO 27001 Annex A and NIST, with a prioritized closure plan."));
children.push(P("These are drafts pending legal review; roles and contacts are placeholders for the operating entity."));

// 10. IAL2 readiness
children.push(H1("10. IAL2 Readiness"));
children.push(P("Standing against the IAL2 proofing steps (met / partial / gap):"));
children.push(table([720, 5340, 3300], [
  ["#", "IAL2 step", "Status"],
  ["1", "Resolution (core attributes → one identity)", "Met"],
  ["2", "Evidence collection (strong/superior)", "Met"],
  ["3", "Evidence validation (genuine & valid)", "Partial (no authoritative-source check)"],
  ["4", "Biometric binding + liveness", "Partial (performance not lab-proven)"],
  ["5", "Address/contact confirmation (enrollment code)", "Met"],
  ["6", "Notification of proofing", "Met"],
  ["7", "Biometric performance (FMR ≤ 1:10,000; PAD)", "Gap (data + lab)"],
  ["8", "Fraud / injection resistance (unattended)", "Partial (no device attestation)"],
  ["9", "Records & PII security", "Met"],
  ["10", "Independent assessment", "Gap (external)"],
]));
children.push(P("What remains is classified by owner, and none of it is application code: **data** (a genuine document-to-selfie dataset to measure FMR), **integration** (authoritative-source validation), **external + budget** (an ISO 30107-3 PAD test, a demographic-bias study, and an accredited IAL2 assessment), and **infrastructure** (in-region, hardened hosting)."));

// 11. Roadmap
children.push(H1("11. Roadmap to Certification"));
children.push(NUM("**Phase 0–1 — Prototype & measure.** Working end-to-end product; begin real accuracy measurement (face matching benchmarked; operational FMR pending data)."));
children.push(NUM("**Phase 2 — Production hardening.** Encryption, cancelable templates, key management, authentication, session security, audit logging, consent/retention/deletion, dependency scanning — implemented. Remaining: in-region hosting, managed KMS, PostgreSQL hardening, backups/DR."));
children.push(NUM("**Phase 3 — Pre-certification readiness.** Controls-to-standards mapping, ISMS policies, and an internal gap assessment — drafted."));
children.push(NUM("**Phase 4 — Independent assessment.** ISO 30107-3 PAD lab, ISO 27001 / SOC 2, NIST IAL2 assessment, and a penetration test."));
children.push(NUM("**Phase 5 — Maintain.** Monitoring, periodic re-testing, and re-certification."));

// 12. Limitations
children.push(H1("12. Limitations & Honest Status"));
children.push(BULLET("**Not certified.** No IAL2/ISO/SOC 2 assessment has been completed; alignment is self-assessed."));
children.push(BULLET("**Accuracy unproven at the IAL2 bar.** The operational FMR/FRR on genuine pairs is not yet measured."));
children.push(BULLET("**Public demo is sample-only.** Real identity documents must not be used on the hosted demo; real data requires in-region, hardened hosting."));
children.push(BULLET("**Pretrained models.** Core models are open and pretrained; the priority is measurement and tuning, with optional anti-spoof fine-tuning."));

// 13. Conclusion
children.push(H1("13. Conclusion"));
children.push(P("Kyron demonstrates that a standards-aligned eKYC platform can be built with a rigorous security and privacy foundation and honest, evidence-backed governance. Every IAL2 requirement satisfiable in software is in place and tested. The path from here to a defensible IAL2 claim is a matter of data, two integrations, independent assessment, and hosting — decisions and investment rather than further feature development."));

children.push(new Paragraph({ spacing: { before: 240 }, border: { top: { style: BorderStyle.SINGLE, size: 6, color: GOLD, space: 6 } },
  children: [new TextRun({ text: "Supporting documents: controls-standards-mapping, IAL2 readiness brief, in-region hosting plan, dataset-collection plan, ISMS policy set (data-protection, DPIA, incident-response, gap assessment), and SECURITY.md.", italics: true, size: 18, color: MUTE })] }));

// --- assemble --------------------------------------------------------------
const doc = new Document({
  creator: "Kyron project team",
  title: "Kyron eKYC White Paper (Draft)",
  styles: {
    default: { document: { run: { font: "Arial", size: 21, color: "1A1A1A" } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 30, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 300, after: 140 }, outlineLevel: 0,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: "DBE2EF", space: 4 } } } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 24, bold: true, color: NAVY, font: "Arial" },
        paragraph: { spacing: { before: 200, after: 100 }, outlineLevel: 1 } },
    ],
  },
  numbering: {
    config: [
      { reference: "b", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 500, hanging: 260 } } } }] },
      { reference: "n", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
        style: { paragraph: { indent: { left: 500, hanging: 300 } } } }] },
    ],
  },
  sections: [{
    properties: { page: { size: { width: 12240, height: 15840 }, margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({
      alignment: AlignmentType.CENTER,
      border: { top: { style: BorderStyle.SINGLE, size: 4, color: "DBE2EF", space: 6 } },
      children: [
        new TextRun({ text: "Kyron eKYC — White Paper (Draft)   ·   Page ", size: 16, color: MUTE }),
        new TextRun({ children: [PageNumber.CURRENT], size: 16, color: MUTE }),
        new TextRun({ text: " of ", size: 16, color: MUTE }),
        new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: MUTE }),
      ],
    })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log("wrote", OUT, buf.length, "bytes"); });
