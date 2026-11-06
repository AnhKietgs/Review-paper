import type { Run } from "@/lib/api/types";

const phases: Record<string, [string, string]> = {
  planning: ["Supervisor đang chọn công việc", "Xác định tác vụ tiếp theo từ tiến độ và các việc còn lại."],
  preparing: ["Đang chuẩn bị bước tiếp theo", "Tiến độ gần nhất đã được lưu; đang chờ worker cập nhật công việc tiếp theo."],
  next_batch: ["Đang lấy đoạn tài liệu tiếp theo", "Chuẩn bị nội dung để phân tích."],
  analyze: ["Đang phân tích paper", "Phân tích mục tiêu, phương pháp, đóng góp và kết quả từ tài liệu."],
  compare: ["Đang so sánh công trình liên quan", "Đối chiếu paper chính với các công trình bạn đã chọn."],
  verify: ["Đang kiểm chứng nhận xét", "Đánh giá mức độ hỗ trợ của bằng chứng cho các nhận xét đang chờ."],
  repair: ["Đang sửa nhận xét", "Thu hẹp hoặc điều chỉnh nhận xét để khớp bằng chứng nguồn."],
  audit_omission: ["Đang rà thiếu thông tin", "Kiểm tra các chủ đề còn thiếu trên toàn bộ văn bản paper chính."],
  finish: ["Đang hoàn thiện bản review", "Tổng hợp kết quả và phạm vi đã kiểm tra."],
  waiting_quota: ["Đang chờ quota Groq", "Công việc đang tạm chờ hạn mức. Hệ thống sẽ thử tiếp tục khi đến thời điểm được phép gọi Groq."],
  queued: ["Đang chờ đến lượt xử lý", "Worker sẽ bắt đầu khi lượt xử lý hiện tại kết thúc."],
  completed: ["Review đã hoàn tất", "Mở bản review để xem kết quả và trạng thái bằng chứng."],
  failed: ["Lần chạy đã dừng do lỗi", "Xem thông báo và nhật ký thực thi để biết nguyên nhân."],
  interrupted: ["Lần chạy bị gián đoạn", "Bạn có thể tiếp tục từ checkpoint đã lưu."],
  incomplete: ["Đã chạm giới hạn xử lý", "Kết quả chưa hoàn chỉnh; xem phạm vi đọc và công việc còn lại bên dưới."],
  cancelled: ["Lần chạy đã được hủy", "Worker không tiếp tục xử lý bản review này."],
};

export function actionLabel(action: string | null | undefined): string {
  return action && phases[action] ? phases[action][0].replace(/^Đang /, "") : "công việc đang dang dở";
}

export function RunProgress({ run, waiting, lastPollAt, clock, disconnected }: {
  run: Run; waiting: boolean; lastPollAt: number | null; clock: number; disconnected: boolean;
}) {
  const activity = run.activity;
  const phase = waiting ? "waiting_quota" : activity?.phase ?? (run.status === "running" ? "preparing" : run.status);
  const [title, description] = phases[phase] ?? ["Đang cập nhật tiến độ", "Chờ phản hồi từ hệ thống."];
  const work = activity?.work;
  const coverage = work?.paper_read ?? { done: run.processed, total: run.processed + run.remaining };
  const active = ["queued", "running"].includes(run.status);
  const age = lastPollAt === null ? null : Math.max(0, Math.floor((clock - lastPollAt) / 1000));
  return <section className="panel work-progress" aria-labelledby="work-progress-title">
    <div className="spread work-progress-heading">
      <div role="status" aria-live="polite" aria-atomic="true">
        <p className="eyebrow">CÔNG VIỆC HIỆN TẠI</p>
        <h2 id="work-progress-title" data-testid="work-phase">{title}</h2>
        <p className="muted">{description}</p>
      </div>
      <span className="badge">{activity?.source === "live" ? "Trực tiếp từ worker" : "Checkpoint gần nhất"}</span>
    </div>
    {waiting && <p className="work-resume" data-testid="resume-work">Sau khi có quota, tiếp tục: <strong>{actionLabel(activity?.resume_action)}</strong>.</p>}
    <div className="work-coverage">
      <div className="spread"><strong>Phạm vi đọc paper chính</strong><span data-testid="paper-coverage">{coverage.done} / {coverage.total} đoạn</span></div>
      {coverage.total > 0 && <progress aria-label="Phạm vi đọc paper chính" value={coverage.done} max={coverage.total}/>}
      <small>{coverage.total > 0 && coverage.done === coverage.total ? "Đã đọc hết paper chính. Các bước kiểm chứng, sửa nhận xét và rà thiếu thông tin được theo dõi riêng." : "Đây là tiến độ đọc tài liệu, không phải phần trăm hoàn thành toàn bộ review."}</small>
    </div>
    {work && <div className="work-counts">
      <div><strong>{work.findings.pending_verification}</strong><span>Nhận xét chờ kiểm chứng</span></div>
      <div><strong>{work.findings.pending_repairs}</strong><span>Nhận xét chờ sửa</span></div>
      <div><strong>{work.findings.repair_attempts}</strong><span>Lượt sửa đã thực hiện</span></div>
      <div><strong>{work.references.done} / {work.references.total}</strong><span>Công trình đã xử lý đối chiếu</span></div>
    </div>}
    {work && work.omission_audit.topics_pending > 0 && <div className="work-audit" data-testid="omission-progress">
      <strong>Rà thiếu thông tin: {work.omission_audit.checked_chunks} / {work.omission_audit.total_chunks} đoạn đã kiểm tra cho nhóm hiện tại</strong>
      <span>{work.omission_audit.group_topics} chủ đề trong nhóm · {work.omission_audit.topics_pending} chủ đề còn chờ hoàn tất rà soát.</span>
    </div>}
    {active && <small className={disconnected || age === null || age >= 5 ? "work-stale" : "muted"} data-testid="work-freshness">
      {disconnected ? "Mất kết nối cập nhật. Đang hiển thị dữ liệu gần nhất và tự kết nối lại…" : age === null ? "Đang kết nối cập nhật…" : `Nhận cập nhật từ backend ${age} giây trước.`}
    </small>}
  </section>;
}
