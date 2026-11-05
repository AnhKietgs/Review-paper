import Link from "next/link";
import { Icon, type IconName } from "@/components/icons";

const steps: { number: string; title: string; description: string; href: string; icon: IconName; label: string }[] = [
  { number: "01", title: "Chuẩn bị tài liệu", description: "Tải PDF hoặc DOCX có văn bản. Tự chọn công trình liên quan.", href: "/papers", icon: "upload", label: "Mở thư viện paper" },
  { number: "02", title: "Xây dựng tiêu chí", description: "Tạo rubric với các câu hỏi định tính, phù hợp với lĩnh vực.", href: "/rubrics", icon: "rubric", label: "Thiết lập rubric" },
  { number: "03", title: "Review & kiểm chứng", description: "Theo dõi quá trình phân tích và tải báo cáo AI khi hoàn tất.", href: "/reviews", icon: "review", label: "Tạo bản review" },
];

export default function Home() {
  return <>
    <section className="hero">
      <div className="hero-copy"><span className="badge hero-badge"><Icon name="activity" size={14}/>PAPER REVIEW · MVP</span><h1>Từ bài báo gốc đến bản review có thể kiểm chứng.</h1><p>Bạn chọn tài liệu và tiêu chí. Hệ thống gọi từng agent khi cần, tự kiểm tra nhận xét và tạo báo cáo kèm trạng thái bằng chứng.</p><Link className="button" href="/papers">Bắt đầu với thư viện<Icon name="arrow" size={18}/></Link><div className="hero-details"><span><Icon name="papers" size={16}/>PDF & DOCX</span><span><Icon name="check" size={16}/>Trích dẫn từ nguồn gốc</span></div></div>
      <div className="hero-flow" aria-label="Tài liệu được Supervisor điều phối phân tích, so sánh và kiểm chứng để tạo báo cáo">
        <div className="flow-source"><span className="flow-icon"><Icon name="review" size={22}/></span><div><strong>Tài liệu của bạn</strong><small>PDF / DOCX · Paper chính & đối chiếu</small></div></div>
        <div className="flow-line" aria-hidden="true"/>
        <div className="flow-supervisor"><span className="flow-icon"><Icon name="activity" size={22}/></span><div><strong>Supervisor</strong><small>Gọi từng agent theo nhu cầu</small></div><span className="flow-tag">Điều phối</span></div>
        <div className="flow-line" aria-hidden="true"/>
        <div className="flow-agents"><span><Icon name="papers" size={18}/>Phân tích</span><span><Icon name="overview" size={18}/>So sánh</span><span><Icon name="check" size={18}/>Kiểm chứng</span></div>
        <div className="flow-line" aria-hidden="true"/>
        <div className="flow-result"><span className="flow-result-icon"><Icon name="check" size={22}/></span><div><strong>Bản review có bằng chứng</strong><small>Truy xuất nhận xét về đúng nguồn</small></div></div>
      </div>
    </section>
    <div className="section-heading"><div><p className="eyebrow">BẮT ĐẦU NGHIÊN CỨU</p><h2>Ba bước để tạo bản review</h2></div><span className="muted">Từ tài liệu đến nhận xét có nguồn</span></div>
    <div className="cards">{steps.map(step => <Link className="panel step-card" href={step.href} key={step.number}><div className="step-card-top"><span className="step-icon"><Icon name={step.icon} size={23}/></span><span className="step-number">{step.number}</span></div><h3>{step.title}</h3><p>{step.description}</p><span className="step-link">{step.label}<Icon name="arrow" size={17}/></span></Link>)}</div>
  </>;
}
