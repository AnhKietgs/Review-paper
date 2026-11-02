import Link from "next/link";

export default function Home() {
  return <><section className="hero"><div><span className="badge">PAPER REVIEW · MVP</span><h2>Từ bài báo gốc đến bản review có thể kiểm chứng.</h2><p>Bạn chọn tài liệu và tiêu chí. Hệ thống gọi từng agent khi cần, tự kiểm tra nhận xét và tạo báo cáo kèm trạng thái bằng chứng.</p><Link className="button" href="/papers">Bắt đầu với thư viện →</Link></div><div className="hero-flow">TÀI LIỆU GỐC<div>Supervisor</div><span>↓ gọi theo nhu cầu</span><div>Phân tích · So sánh · Kiểm chứng</div><span>↓ tự sửa và kiểm tra nguồn</span><div>Bản review có bằng chứng</div></div></section>
    <div className="cards">{[["01", "Chuẩn bị", "Tải PDF hoặc DOCX có văn bản. Tự chọn công trình liên quan.", "/papers"], ["02", "Đặt tiêu chí", "Tạo rubric với các câu hỏi định tính, phù hợp với lĩnh vực.", "/rubrics"], ["03", "Review & kiểm chứng", "Theo dõi harness và tải báo cáo AI khi hoàn tất.", "/reviews"]].map(([n,t,d,h]) => <Link className="panel step-card" href={h} key={n}><span className="step-number">{n}</span><h2>{t}</h2><p>{d}</p><span>Đi đến bước này →</span></Link>)}</div>
  </>;
}
