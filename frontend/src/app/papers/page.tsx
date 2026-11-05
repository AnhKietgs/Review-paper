"use client";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PageHeader, ErrorBanner } from "@/components/shell";
import { api, errorMessage } from "@/lib/api/client";
import type { Page, Paper } from "@/lib/api/types";

export default function Papers() {
  const [papers, setPapers] = useState<Paper[]>([]);
  const [selected, setSelected] = useState<Paper | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const load = useCallback(async () => { const data = await api<Page<Paper>>(`/papers?offset=${offset}`); setPapers(data.items); setTotal(data.total); }, [offset]);
  useEffect(() => { load().catch(e => setError(errorMessage(e))); }, [load]);
  async function upload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; setBusy(true); setError("");
    try { const result = await api<Paper>("/papers", { method: "POST", body: new FormData(form) }); setSelected(result); form.reset(); await load(); }
    catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function update(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selected) return; setBusy(true); setError("");
    const data = new FormData(event.currentTarget); const file = data.get("file") as File;
    if (!file?.size) data.delete("file");
    try { setSelected(await api<Paper>(`/papers/${selected.id}`, { method: "PATCH", body: data })); await load(); }
    catch(e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function remove(paper: Paper) {
    if (!window.confirm(`Xóa “${paper.title}” khỏi thư viện? Bằng chứng cũ vẫn được giữ.`)) return;
    try { await api(`/papers/${paper.id}`, { method: "DELETE" }); if (selected?.id === paper.id) setSelected(null); await load(); } catch(e) { setError(errorMessage(e)); }
  }
  return <><PageHeader eyebrow="02 / TÀI LIỆU" title="Thư viện tài liệu" description="Tải tài liệu gốc lên một lần, dùng cho nhiều bản review." /><ErrorBanner message={error} />
    <div className="two-columns"><section><form className="panel" onSubmit={upload}><h2>Thêm bài báo</h2><label>Tiêu đề paper<input name="title" required maxLength={500}/></label><label>Tác giả<input name="authors" placeholder="Phân cách bằng dấu phẩy"/></label><label>Tệp PDF hoặc DOCX<input name="file" type="file" accept=".pdf,.docx" required/></label><p><small>PDF scan chưa có OCR không thuộc MVP.</small></p><button disabled={busy}>Tải lên thư viện</button></form>
    <section className="panel"><h2>Tài liệu của bạn <small>({total})</small></h2>{!papers.length && <p className="empty">Chưa có tài liệu trong trang này.</p>}{papers.map(p => <div className="list-row" key={p.id}><button className="text-button" onClick={() => api<Paper>(`/papers/${p.id}`).then(setSelected).catch(e => setError(errorMessage(e)))}>{p.title}</button><small>{p.original_filename} · v{p.content_version}</small><div className="actions"><button className="text-button danger" onClick={() => remove(p)}>Xóa khỏi thư viện</button></div></div>)}<div className="actions"><button className="secondary" disabled={!offset} onClick={() => setOffset(offset - 20)}>Trước</button><button className="secondary" disabled={offset + 20 >= total} onClick={() => setOffset(offset + 20)}>Sau</button></div></section></section>
    <section className="panel">{selected ? <><div className="spread"><h2>{selected.title}</h2><span className="badge">v{selected.content_version}</span></div><form key={`${selected.id}-${selected.content_version}`} onSubmit={update}><label>Sửa tiêu đề<input name="title" defaultValue={selected.title} required/></label><label>Thay tệp nguồn (tùy chọn)<input name="file" type="file" accept=".pdf,.docx"/></label><div className="actions"><button className="secondary" disabled={busy}>Lưu tài liệu</button><a href={`/api/v1/papers/${selected.id}/source?version=${selected.content_version}`} target="_blank" rel="noreferrer">Mở tệp gốc ↗</a></div></form><hr/><h3>Nội dung và vị trí nguồn</h3>{selected.chunks.map(c => <div className="source-chunk" key={c.id}><span className="badge">{c.locator?.type} {c.locator?.value} · {c.locator?.status ?? "unresolved"}</span><p>{c.text}</p></div>)}<details><summary>Markdown sau chuyển đổi</summary><pre>{selected.markdown}</pre></details></> : <div className="empty">Chọn một paper để xem nội dung và chỉnh sửa.</div>}</section></div></>;
}
