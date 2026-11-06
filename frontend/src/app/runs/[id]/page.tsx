"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, ErrorBanner } from "@/components/shell";
import { api, errorMessage } from "@/lib/api/client";
import type { Run, RunEvent } from "@/lib/api/types";
import { RunProgress, runErrorMessage } from "@/components/run-progress";

export default function RunInspector() {
  const {id}=useParams<{id:string}>(); const [run,setRun]=useState<Run|null>(null),[events,setEvents]=useState<RunEvent[]>([]);
  const [error,setError]=useState(""),[filter,setFilter]=useState("all"),[resume,setResume]=useState(0);
  const [controlBusy,setControlBusy]=useState<"cancel"|"resume"|null>(null);
  const [lastPollAt,setLastPollAt]=useState<number|null>(null),[clock,setClock]=useState(Date.now());
  const active=!!run&&["queued","running"].includes(run.status);
  useEffect(()=>{if(!active)return;const timer=setInterval(()=>setClock(Date.now()),1000);return()=>clearInterval(timer);},[active]);
  useEffect(()=>{let alive=true;let timer:ReturnType<typeof setTimeout>;let cursor=0;
    async function poll(){try{const [r,e]=await Promise.all([api<Run>(`/runs/${id}`),api<{items:RunEvent[]}>(`/runs/${id}/events?after=${cursor}`)]);if(!alive)return;setRun(r);setLastPollAt(Date.now());setError("");setEvents(prev=>{const ids=new Set(prev.map(x=>x.id));return [...prev,...e.items.filter(x=>!ids.has(x.id))];});if(e.items.length)cursor=e.items[e.items.length-1].sequence;if(["queued","running"].includes(r.status))timer=setTimeout(poll,1000);}catch(e){if(alive){setError(errorMessage(e));timer=setTimeout(poll,3000);}}}
    setEvents([]);setRun(null);setLastPollAt(null);poll();return()=>{alive=false;clearTimeout(timer);};
  },[id,resume]);
  const count=(action:string)=>events.filter(e=>e.action===action).length;
  const permission=events.filter(e=>e.permission_result);
  const roles=[["supervisor","Supervisor"],["scientific_review","Scientific Review"],["related_work","Related-Work Comparator"],["evidence_verifier","Evidence Verifier"]];
  const latestCooldown=[...events].reverse().find(event=>event.action==="provider_cooldown");
  const retryAt=run?.activity?run.activity.retry_at:run?.cooldown_until;
  const waiting=run?.status==="running"&&(run.activity?run.activity.phase==="waiting_quota":!!run.cooldown_until);
  const remainingSeconds=retryAt?Math.max(0,Math.ceil((new Date(retryAt).getTime()-clock)/1000)):0;
  const countdown=`${String(Math.floor(remainingSeconds/60)).padStart(2,"0")}:${String(remainingSeconds%60).padStart(2,"0")}`;
  async function control(action:"cancel"|"resume") {
    setControlBusy(action);setError("");
    try {await api(`/runs/${id}/${action}`,{method:"POST"});setResume(value=>value+1);}
    catch(cause) {setError(errorMessage(cause));}
    finally {setControlBusy(null);}
  }
  return <><PageHeader eyebrow="HARNESS / LIVE INSPECTOR" title="Theo dõi quá trình review" description="Các số liệu và sự kiện lấy từ lần chạy thực tế. Supervisor chọn một hành động; harness kiểm tra quyền, phạm vi và kết quả trước khi tiếp tục."/><ErrorBanner message={error}/>
    {!run?<p>Đang tải lần chạy…</p>:<><div className="panel spread" aria-busy={!!controlBusy}>
      <span data-testid="run-status" role="status" aria-label={run.status === "running" ? (waiting ? "Đang chờ hạn mức Groq" : "Đang chạy review") : run.status} className={`status ${run.status} ${run.status === "running" && !waiting ? "run-live" : ""}`}>{waiting ? "waiting" : run.status}</span>
      <div className="actions">
        {["queued","running"].includes(run.status) ? <span className="run-review-locked">Bản review sẽ mở khi xử lý xong</span> : <Link href={`/reviews/${run.review_id}`}>Mở bản review →</Link>}
        {(run.status==="interrupted"||(run.status==="failed"&&["rate_limited","quota_request_too_large","provider_unavailable","provider_timeout","provider_connection_error"].includes(run.error_code??"")))&&<button disabled={!!controlBusy} onClick={()=>control("resume")}>{controlBusy==="resume"?"Đang tiếp tục…":"Tiếp tục từ checkpoint"}</button>}
        {["queued","running","interrupted","failed"].includes(run.status)&&<button className="danger-button" disabled={!!controlBusy} onClick={()=>control("cancel")}>{controlBusy==="cancel"?"Đang dừng…":"Dừng review"}</button>}
      </div>
    </div>
    {run.status==="cancelled"&&<div className="notice" role="status">Bạn đã dừng lượt review này. Bản review và kết quả đã lưu vẫn được giữ lại.</div>}
    {waiting && <div className="notice cooldown-notice"><strong data-testid="cooldown-countdown">{remainingSeconds>0?`Còn ${countdown} trước lần thử tiếp theo`:"Đã đến thời điểm thử lại; đang chờ cập nhật…"}</strong><span>{run.activity?.source==="live"?"Worker đang chờ hạn mức Groq; công việc chưa hoàn tất.":"Groq đang giới hạn lượt gọi; tiến độ đã được lưu tại checkpoint."}</span><span data-testid="run-heartbeat" className="run-heartbeat">Kết nối backend: {lastPollAt!==null&&clock-lastPollAt<5000?"hoạt động":"đang kiểm tra"}</span>{latestCooldown&&<span data-testid="last-provider-attempt">Lần thử Groq gần nhất: {new Date(latestCooldown.timestamp).toLocaleTimeString("vi-VN",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}</span>}</div>}
    {run.error_code&&run.status!=="cancelled"&&<div className="error">{runErrorMessage(run.error_code)}</div>}
    {run.status==="incomplete"&&<div className="notice">Đã chạm giới hạn xử lý. Kết quả này chưa bao phủ hết tài liệu; hãy chạy một revision mới để tạo báo cáo hoàn chỉnh.</div>}
    <RunProgress run={run} waiting={!!waiting} lastPollAt={lastPollAt} clock={clock} disconnected={!!error}/>
    <div className="metrics">{[[`${run.processed}`,"Đoạn đã đọc"],[`${run.remaining}`,"Đoạn còn lại"],[`${run.step_count} / ${run.max_turns}`,"Lượt xử lý"],[`${run.usage.calls??0}`,"Lượt gọi mô hình"]].map(([v,t])=><div className="metric" key={t}><strong>{v}</strong><span>{t}</span></div>)}</div>
    <section className="panel"><h2>Harness tự xây dựng</h2><div className="harness-grid">{[["Loop",`${run.batch_count}/${run.max_batches} batch · ${run.step_count} lượt`],["Tool",`${count("tool_result")} kết quả trả về`],["Memory",`${count("checkpoint_saved")} sự kiện lưu checkpoint`],["Context",`${count("context_built")} lần dựng ngữ cảnh`],["Permission",`${permission.filter(e=>e.permission_result==="allow").length} cho phép · ${permission.filter(e=>e.permission_result==="deny").length} từ chối`],["Output gate",`${count("validation_passed")+count("validation_failed")+count("finding_verified")} lần kiểm tra đầu ra`]].map(([t,d])=><div className="harness-node" key={t}><strong>{t}</strong>{d}</div>)}</div><div className="harness-loop" aria-label="Vòng lặp điều phối của harness"><span>Supervisor chọn việc</span><span aria-hidden="true">→</span><span>Kiểm tra quyền và dựng context</span><span aria-hidden="true">→</span><span>Gọi agent cần thiết</span><span aria-hidden="true">→</span><span>Output gate và checkpoint</span><strong>↶ Lặp lại đến khi hoàn tất</strong></div><div className="agents">{roles.map(([key,title])=><div className={`agent ${(run.call_counts[key]??0)>0?"used":""} ${run.activity?.source==="live"&&run.activity.agent===key&&!waiting?"agent-current":""}`} key={key}><strong>{title}</strong><span>{run.call_counts[key]??0} lượt gọi</span></div>)}</div><small>Agent có 0 lượt gọi chưa được dùng trong lần chạy này. Sự kiện bên dưới giải thích quyết định và các bước bị bỏ qua.</small></section>
    {Object.keys(run.reference_assessments).length>0&&<section className="panel"><h2>Phạm vi đối chiếu</h2>{Object.entries(run.reference_assessments).map(([key,value])=><div className="list-row" key={key}><span className="mono">{key}</span> · <span className="status">{value.status}</span><p>{value.reason}</p></div>)}</section>}
    <section className="panel"><div className="spread"><h2>Nhật ký thực thi</h2><small>{events.length} sự kiện đã nhận</small></div><label className="filter">Lọc sự kiện<select value={filter} onChange={e=>setFilter(e.target.value)}><option value="all">Tất cả</option>{Array.from(new Set(events.map(e=>e.action))).map(a=><option key={a}>{a}</option>)}</select></label>{events.filter(e=>filter==="all"||e.action===filter).map(e=><details className="event" key={e.id}><summary><span className="mono">#{e.sequence}</span><span className="badge">{e.agent}</span><strong>{e.action}</strong><small>{e.output_summary||e.input_summary}</small></summary><p>{e.tool&&`Tool: ${e.tool} · `}{e.permission_result&&`Permission: ${e.permission_result}`}</p><small>{new Date(e.timestamp).toLocaleString("vi-VN")}</small><pre>{JSON.stringify(e.payload,null,2)}</pre></details>)}</section></>}
  </>;
}
