"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { ErrorBanner, PageHeader } from "@/components/shell";
import { api, errorMessage } from "@/lib/api/client";
import type { AcceptedRun, Evidence, Paper, Review } from "@/lib/api/types";

type FindingFilter = "all" | "unsupported" | "uncertain" | "pending" | "supported";

function findingStatusLabel(status: string) {
  if (status === "supported") return "Có nguồn hỗ trợ";
  if (status === "unsupported") return "Chưa xác minh";
  if (status === "uncertain" || status === "needs_human_review") return "Chưa chắc chắn";
  return "Chờ kiểm chứng";
}

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const sourceHeading = useRef<HTMLHeadingElement>(null);
  const summaryField = useRef<HTMLTextAreaElement>(null);
  const [review, setReview] = useState<Review | null>(null);
  const [paper, setPaper] = useState<Paper | null>(null);
  const [source, setSource] = useState<{ paper: Paper; evidence: Evidence } | null>(null);
  const [filter, setFilter] = useState<FindingFilter>("all");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let alive = true;
    api<Review>(`/reviews/${id}`)
      .then(async (result) => {
        const sourcePaper = await api<Paper>(`/papers/${result.paper_id}/versions/${result.paper_content_version}`);
        if (alive) {
          setReview(result);
          setPaper(sourcePaper);
          setDirty(false);
        }
      })
      .catch((cause) => { if (alive) setError(errorMessage(cause)); });
    return () => { alive = false; };
  }, [id]);

  useLayoutEffect(() => {
    const field = summaryField.current;
    if (!field) return;
    const fitContent = () => {
      field.style.height = "auto";
      const borderHeight = field.offsetHeight - field.clientHeight;
      field.style.height = `${field.scrollHeight + borderHeight}px`;
    };
    fitContent();
    window.addEventListener("resize", fitContent);
    return () => window.removeEventListener("resize", fitContent);
  }, [id, review?.summary]);

  async function act(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setNotice("");
    try { await action(); }
    catch (cause) { setError(errorMessage(cause)); }
    finally { setBusy(false); }
  }

  async function run(mode: string) {
    await act(async () => {
      const result = await api<AcceptedRun>(`/reviews/${id}/runs`, {
        method: "POST", body: JSON.stringify({ mode }),
      });
      router.push(`/runs/${result.run_id}`);
    });
  }

  async function save() {
    if (!review) return;
    await act(async () => {
      const updated = await api<Review>(`/reviews/${id}`, {
        method: "PATCH", body: JSON.stringify({ summary: review.summary, findings: review.findings }),
      });
      setReview(updated);
      setDirty(false);
      setNotice("Đã lưu. Chạy kiểm chứng để AI đánh giá lại nhận xét đã sửa.");
    });
  }

  async function openSource(evidence: Evidence) {
    await act(async () => {
      const sourcePaper = await api<Paper>(`/papers/${evidence.paper_id}/versions/${evidence.content_version}`);
      setSource({ paper: sourcePaper, evidence });
      if (window.matchMedia("(max-width: 1100px)").matches) {
        requestAnimationFrame(() => sourceHeading.current?.focus());
      }
    });
  }

  if (!review) {
    return <>
      <PageHeader eyebrow="REVIEW WORKSPACE" title={error ? "Không tải được bản review" : "Đang tải bản review…"} description="Đọc phiên bản và bằng chứng đã lưu." />
      <ErrorBanner message={error} />
      {error && <Link href="/reviews">← Về danh sách review</Link>}
    </>;
  }

  const locked = ["completed", "approved", "queued", "running", "interrupted"].includes(review.status);
  const statusCount = (status: string) => review.findings.filter((finding) => finding.status === status).length;
  const uncertainCount = statusCount("uncertain") + statusCount("needs_human_review");
  const visibleFindings = review.findings
    .map((finding, index) => ({ finding, index }))
    .filter(({ finding }) => filter === "all" || finding.status === filter || (filter === "uncertain" && finding.status === "needs_human_review"));

  return <>
    <PageHeader
      eyebrow={`REVIEW WORKSPACE / REVISION ${review.revision}`}
      title={paper?.title ?? "Bản review"}
      description={`Paper v${review.paper_content_version} · Rubric v${review.rubric_version} · ${review.references.length} công trình liên quan`}
    />
    <ErrorBanner message={error} />
    {notice && <div role="status" className="notice">{notice}</div>}

    <section className="panel review-overview" aria-label="Trạng thái bản review">
      <div className="spread review-overview-top">
        <span className={`status ${review.status}`}>{review.status}</span>
        <span className="mono" title={id}>Mã {id.slice(0, 8)}</span>
      </div>
      <div className="actions" aria-busy={busy}>
        <button disabled={busy || dirty || ["queued", "running", "interrupted"].includes(review.status)} onClick={() => run("review")}>Chạy Paper Review</button>
        {!locked && review.findings.length > 0 && <button className="secondary" disabled={busy || dirty} onClick={() => run("verify")}>Kiểm chứng bản sửa</button>}
        <button className="secondary" disabled={busy || dirty} onClick={() => act(async () => {
          const result = await api<Review>(`/reviews/${id}/revisions`, { method: "POST" });
          router.push(`/reviews/${result.id}`);
        })}>Tạo revision mới</button>
        {["completed", "approved"].includes(review.status) && <a className="button" download href={`/api/v1/reviews/${id}/export.md`}>Tải báo cáo AI</a>}
        <Link href="/reviews">← Danh sách review</Link>
      </div>
      <p className="helper-text">{dirty ? "Có thay đổi chưa lưu. Lưu trước khi chạy kiểm chứng." : "AI hoàn tất và tạo báo cáo sau khi kiểm tra bằng chứng. Muốn chỉnh sửa, hãy tạo revision mới."}</p>
    </section>

    <section className="review-summary" aria-label="Tổng quan nhận xét">
      <div className="summary-item"><strong>{review.findings.length}</strong><span>Tổng nhận xét</span></div>
      <div className="summary-item"><strong>{statusCount("supported")}</strong><span>Có nguồn hỗ trợ</span></div>
      <div className="summary-item"><strong>{statusCount("unsupported")}</strong><span>Thiếu bằng chứng</span></div>
      <div className="summary-item"><strong>{statusCount("pending") + uncertainCount}</strong><span>Chưa chắc chắn / chờ kiểm tra</span></div>
    </section>

    <div className="review-layout">
      <section className="panel review-content" aria-labelledby="review-content-title">
        <div className="review-section-head">
          <div>
            <h2 id="review-content-title">Nội dung đánh giá</h2>
          </div>
          {review.findings.length > 0 && <label className="finding-filter">Lọc nhận xét
            <select value={filter} onChange={(event) => setFilter(event.target.value as FindingFilter)}>
              <option value="all">Tất cả ({review.findings.length})</option>
              <option value="unsupported">Thiếu bằng chứng ({statusCount("unsupported")})</option>
              <option value="uncertain">Chưa chắc chắn ({uncertainCount})</option>
              <option value="pending">Chờ kiểm chứng ({statusCount("pending")})</option>
              <option value="supported">Có nguồn hỗ trợ ({statusCount("supported")})</option>
            </select>
          </label>}
        </div>

        <label>Tóm tắt biên tập
          <textarea ref={summaryField} className="summary-textarea" rows={3} disabled={locked} value={review.summary} onChange={(event) => {
            setReview({ ...review, summary: event.target.value });
            setDirty(true);
          }} />
        </label>
        {!review.findings.length && <p className="empty">Chạy Paper Review để tạo nhận xét và kiểm tra bằng chứng.</p>}
        {!!review.findings.length && !visibleFindings.length && <p className="empty">Không có nhận xét ở trạng thái này. Hãy chọn bộ lọc khác.</p>}

        {visibleFindings.map(({ finding, index }) => <article className="finding" key={finding.id}>
          <div className="finding-heading">
            <div><span className="finding-index">NHẬN XÉT {index + 1}</span><h3>{finding.criterion_code.replaceAll("_", " ")}</h3></div>
            <span className={`status ${finding.status}`}>{findingStatusLabel(finding.status)}</span>
          </div>
          <label>Nhận xét {index + 1}
            <textarea disabled={locked} value={finding.claim} onChange={(event) => {
              setReview({ ...review, findings: review.findings.map((item, itemIndex) => itemIndex === index ? { ...item, claim: event.target.value } : item) });
              setDirty(true);
            }} />
          </label>
          <p className="finding-meta">{finding.kind} · {finding.verdict}</p>
          {finding.evidence.map((evidence, evidenceIndex) => <div className="evidence-item" key={`${evidence.chunk_id}-${evidenceIndex}`}>
            <blockquote>{evidence.quote}</blockquote>
            <button className="text-button source-link" disabled={busy} onClick={() => openSource(evidence)}>
              Xem nguồn {evidenceIndex + 1} · {evidence.locator_type} {evidence.locator_value} · v{evidence.content_version} ↗
            </button>
          </div>)}
        </article>)}

        {!locked && <div className="actions review-final-actions">
          <button className="secondary" disabled={busy || !dirty} onClick={save}>Lưu chỉnh sửa</button>
        </div>}
        <details className="analysis-details"><summary>Phân tích và phạm vi đọc</summary><pre>{JSON.stringify(review.analysis, null, 2)}</pre></details>
      </section>

      <section className="panel source-viewer" data-testid="source-viewer" aria-labelledby="source-viewer-title">
        <h2 id="source-viewer-title" ref={sourceHeading} tabIndex={-1}>Đối chiếu tài liệu gốc</h2>
        {source ? <>
          <h3>{source.paper.title}</h3>
          <p><span className="badge">v{source.evidence.content_version} · {source.evidence.locator_type} {source.evidence.locator_value}</span></p>
          <a href={`/api/v1/papers/${source.paper.id}/source?version=${source.evidence.content_version}`} target="_blank" rel="noreferrer">Mở / tải tệp gốc ↗</a>
          {source.paper.media_type === "application/pdf" && <iframe title="Tài liệu PDF gốc" src={`/api/v1/papers/${source.paper.id}/source?version=${source.evidence.content_version}#page=${source.evidence.locator_value}`} />}
          <div className="source-chunk highlight">{source.paper.chunks.find((chunk) => chunk.id === source.evidence.chunk_id)?.text ?? "Không tìm thấy đoạn nguồn."}</div>
          <p className="helper-text">Vị trí lấy từ phiên bản tài liệu lúc chạy review.</p>
        </> : <div className="source-empty"><span className="source-empty-mark" aria-hidden="true">↗</span><p>Chọn “Xem nguồn” dưới một nhận xét để đối chiếu nội dung gốc tại đây.</p></div>}
      </section>
    </div>
  </>;
}
