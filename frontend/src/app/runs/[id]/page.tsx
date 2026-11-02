"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, ErrorBanner } from "@/components/shell";
import { api, errorMessage } from "@/lib/api/client";
import type { Run, RunEvent } from "@/lib/api/types";

export default function RunInspector() {
  const {id}=useParams<{id:string}>(); const [run,setRun]=useState<Run|null>(null),[events,setEvents]=useState<RunEvent[]>([]);
  const [error,setError]=useState(""),[filter,setFilter]=useState("all"),[resume,setResume]=useState(0);
  useEffect(()=>{let alive=true;let timer:ReturnType<typeof setTimeout>;let cursor=0;
    async function poll(){try{const [r,e]=await Promise.all([api<Run>(`/runs/${id}`),api<{items:RunEvent[]}>(`/runs/${id}/events?after=${cursor}`)]);if(!alive)return;setRun(r);setError("");setEvents(prev=>{const ids=new Set(prev.map(x=>x.id));return [...prev,...e.items.filter(x=>!ids.has(x.id))];});if(e.items.length)cursor=e.items[e.items.length-1].sequence;if(["queued","running"].includes(r.status))timer=setTimeout(poll,1000);}catch(e){if(alive){setError(errorMessage(e));timer=setTimeout(poll,3000);}}}
    setEvents([]);poll();return()=>{alive=false;clearTimeout(timer);};
  },[id,resume]);
  const count=(action:string)=>events.filter(e=>e.action===action).length;
  const permission=events.filter(e=>e.permission_result);
  const roles=[["supervisor","Supervisor"],["scientific_review","Scientific Review"],["related_work","Related-Work Comparator"],["evidence_verifier","Evidence Verifier"]];
  return <><PageHeader eyebrow="HARNESS / LIVE INSPECTOR" title="Theo dõi quá trình review" description="Các số liệu và sự kiện lấy từ lần chạy thực tế. Supervisor chọn một hành động; harness kiểm tra quyền, phạm vi và kết quả trước khi tiếp tục."/><ErrorBanner message={error}/>
    {!run?<p>Đang tải lần chạy…</p>:<><div className="panel spread"><span data-testid="run-status" className={`status ${run.status}`}>{run.status}</span><Link href={`/reviews/${run.review_id}`}>Mở bản review →</Link>{run.status==="interrupted"&&<button onClick={async()=>{try{await api(`/runs/${id}/resume`,{method:"POST"});setResume(resume+1);}catch(e){setError(errorMessage(e));}}}>Tiếp tục từ checkpoint</button>}</div>
    {run.error_code&&<div className="error">Lần chạy dừng: {run.error_code}. Xem trace bên dưới trước khi chạy revision mới.</div>}
    {run.status==="incomplete"&&<div className="notice">Đã chạm giới hạn xử lý. Kết quả này chưa bao phủ hết tài liệu; hãy chạy một revision mới để tạo báo cáo hoàn chỉnh.</div>}
    <div className="metrics">{[[`${run.processed}`,"Đoạn đã đọc"],[`${run.remaining}`,"Đoạn còn lại"],[`${run.step_count} / ${run.max_turns}`,"Lượt xử lý"],[`${run.usage.calls??0}`,"Lượt gọi mô hình"]].map(([v,t])=><div className="metric" key={t}><strong>{v}</strong><span>{t}</span></div>)}</div>
    <section className="panel"><h2>Harness tự xây dựng</h2><div className="harness-grid">{[["Loop",`${run.batch_count}/${run.max_batches} batch · ${run.step_count} lượt`],["Tool",`${count("tool_result")} kết quả trả về`],["Memory",`${count("checkpoint_saved")} sự kiện lưu checkpoint`],["Context",`${count("context_built")} lần dựng ngữ cảnh`],["Permission",`${permission.filter(e=>e.permission_result==="allow").length} cho phép · ${permission.filter(e=>e.permission_result==="deny").length} từ chối`],["Output gate",`${count("validation_passed")+count("validation_failed")+count("finding_verified")} lần kiểm tra đầu ra`]].map(([t,d])=><div className="harness-node" key={t}><strong>{t}</strong>{d}</div>)}</div><div className="harness-loop" aria-label="Vòng lặp điều phối của harness"><span>Supervisor chọn việc</span><span aria-hidden="true">→</span><span>Kiểm tra quyền và dựng context</span><span aria-hidden="true">→</span><span>Gọi agent cần thiết</span><span aria-hidden="true">→</span><span>Output gate và checkpoint</span><strong>↶ Lặp lại đến khi hoàn tất</strong></div><div className="agents">{roles.map(([key,title])=><div className={`agent ${(run.call_counts[key]??0)>0?"used":""}`} key={key}><strong>{title}</strong><span>{run.call_counts[key]??0} lượt gọi</span></div>)}</div><small>Agent có 0 lượt gọi chưa được dùng trong lần chạy này. Sự kiện bên dưới giải thích quyết định và các bước bị bỏ qua.</small></section>
    {Object.keys(run.reference_assessments).length>0&&<section className="panel"><h2>Phạm vi đối chiếu</h2>{Object.entries(run.reference_assessments).map(([key,value])=><div className="list-row" key={key}><span className="mono">{key}</span> · <span className="status">{value.status}</span><p>{value.reason}</p></div>)}</section>}
    <section className="panel"><div className="spread"><h2>Nhật ký thực thi</h2><small>{events.length} sự kiện đã nhận</small></div><label className="filter">Lọc sự kiện<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">Tất cả</option>{Array.from(new Set(events.map(e=>e.action))).map(a=><option key={a}>{a}</option>)}</select></label>{events.filter(e=>filter==="all"||e.action===filter).map(e=><details className="event" key={e.id}><summary><span className="mono">#{e.sequence}</span><span className="badge">{e.agent}</span><strong>{e.action}</strong><small>{e.output_summary||e.input_summary}</small></summary><p>{e.tool&&`Tool: ${e.tool} · `}{e.permission_result&&`Permission: ${e.permission_result}`}</p><small>{new Date(e.timestamp).toLocaleString("vi-VN")}</small><pre>{JSON.stringify(e.payload,null,2)}</pre></details>)}</section></>}
  </>;
}
