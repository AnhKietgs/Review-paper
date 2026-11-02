"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { PageHeader, ErrorBanner } from "@/components/shell";
import { api, errorMessage } from "@/lib/api/client";
import type { Page, Paper, Rubric, Review } from "@/lib/api/types";

async function all<T>(path: string): Promise<T[]> { const result: T[] = []; let page: Page<T>; do { page = await api<Page<T>>(`${path}?limit=100&offset=${result.length}`); result.push(...page.items); } while(result.length < page.total && page.items.length); return result; }
export default function Reviews() {
  const router = useRouter();
  const [papers, setPapers] = useState<Paper[]>([]), [rubrics, setRubrics] = useState<Rubric[]>([]), [reviews, setReviews] = useState<Review[]>([]);
  const [paper, setPaper] = useState(""), [rubric, setRubric] = useState(""), [refs, setRefs] = useState<string[]>([]);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false), [offset, setOffset] = useState(0), [total, setTotal] = useState(0);
  const load = useCallback(async () => { const d = await api<Page<Review>>(`/reviews?offset=${offset}`); setReviews(d.items); setTotal(d.total); }, [offset]);
  useEffect(() => { Promise.all([all<Paper>("/papers"),all<Rubric>("/rubrics")]).then(([p,r]) => {setPapers(p);setRubrics(r);}).catch(e=>setError(errorMessage(e))); }, []);
  useEffect(() => { load().catch(e=>setError(errorMessage(e))); }, [load]);
  async function create(e: FormEvent) { e.preventDefault(); setBusy(true); setError(""); try { const r = await api<Review>("/reviews",{method:"POST",body:JSON.stringify({paper_id:paper,rubric_id:rubric,reference_paper_ids:refs})}); router.push(`/reviews/${r.id}`); } catch(e) {setError(errorMessage(e));setBusy(false);} }
  async function remove(r: Review) { if(!window.confirm(`Xóa bản review revision ${r.revision}?`)) return; try {await api(`/reviews/${r.id}`,{method:"DELETE"});await load();}catch(e){setError(errorMessage(e));} }
  return <><PageHeader eyebrow="04 / REVIEW" title="Bản review" description="Chọn một bài báo chính, rubric và các công trình đối chiếu. Mỗi lần chạy tạo một revision riêng để giữ lại lịch sử."/><ErrorBanner message={error}/><div className="two-columns"><form className="panel" onSubmit={create}><h2>Chuẩn bị bản review</h2><label>Paper chính<select required value={paper} onChange={e=>{setPaper(e.target.value);setRefs(refs.filter(id=>id!==e.target.value));}}><option value="">Chọn bài báo</option>{papers.map(p=><option key={p.id} value={p.id}>{p.title}</option>)}</select></label><label>Rubric đánh giá<select required value={rubric} onChange={e=>setRubric(e.target.value)}><option value="">Chọn bộ tiêu chí</option>{rubrics.map(r=><option key={r.id} value={r.id}>{r.name}</option>)}</select></label><fieldset><legend>Công trình liên quan · tùy chọn</legend>{papers.filter(p=>p.id!==paper).map(p=><label key={p.id} className="inline"><input type="checkbox" checked={refs.includes(p.id)} onChange={e=>setRefs(e.target.checked?[...refs,p.id]:refs.filter(id=>id!==p.id))}/>{p.title}</label>)}<small>Chỉ những tài liệu được chọn mới được phép dùng để so sánh.</small></fieldset><button disabled={busy || !paper || !rubric}>Tạo bản nháp</button></form><section className="panel"><h2>Lịch sử review ({total})</h2>{!reviews.length && <p className="empty">Bản review đầu tiên sẽ xuất hiện tại đây.</p>}{reviews.map(r=><div className="list-row" key={r.id}><Link href={`/reviews/${r.id}`}>{papers.find(p=>p.id===r.paper_id)?.title ?? "Paper đã lưu trữ"}</Link><small>Revision {r.revision} · {r.findings.length} nhận xét · <span className={`status ${r.status}`}>{r.status}</span></small><button className="text-button" onClick={()=>remove(r)}>Xóa bản review</button></div>)}<div className="actions"><button className="secondary" disabled={!offset} onClick={()=>setOffset(offset-20)}>Trước</button><button className="secondary" disabled={offset+20>=total} onClick={()=>setOffset(offset+20)}>Sau</button></div></section></div></>;
}
