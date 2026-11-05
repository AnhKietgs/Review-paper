"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api/client";
import { Icon, type IconName } from "@/components/icons";

const navigation: { url: string; title: string; icon: IconName }[] = [
  { url: "/", title: "Tổng quan", icon: "overview" },
  { url: "/papers", title: "Thư viện paper", icon: "papers" },
  { url: "/rubrics", title: "Rubric đánh giá", icon: "rubric" },
  { url: "/reviews", title: "Bản review", icon: "review" },
];

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [mode, setMode] = useState("đang kết nối");
  useEffect(() => { api<{llm_mode: string}>("/runtime").then(r => setMode(r.llm_mode)).catch(() => setMode("offline")); }, []);
  const currentTitle = path.startsWith("/runs") ? "Tiến trình review" : navigation.find(item => item.url !== "/" && path.startsWith(item.url))?.title ?? "Tổng quan";
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Đi tới nội dung chính</a>
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark"><Icon name="papers" size={24}/></span><span>Paper Review<small>RESEARCH WORKSPACE</small></span></Link>
      <p className="nav-label">KHÔNG GIAN LÀM VIỆC</p>
      <nav aria-label="Điều hướng chính">{navigation.map(({ url, title, icon }) => {
        const active = path === url || (url !== "/" && path.startsWith(url)) || (url === "/reviews" && path.startsWith("/runs"));
        return <Link className={active ? "active" : ""} aria-current={active ? "page" : undefined} key={url} href={url}><Icon name={icon}/><span>{title}</span><span className="nav-current-indicator" aria-hidden="true"/></Link>;
      })}</nav>
      <div className="sidebar-footer">
        <div className="environment-card"><span className={`badge environment-mode ${mode === "offline" ? "offline" : ""}`}><span className="environment-dot" aria-hidden="true"/>{mode.toUpperCase()}</span><p>{mode === "fixture" ? "Trả lời mô phỏng để kiểm tra quy trình. Không dùng như đánh giá khoa học." : mode === "groq" ? "Phân tích qua Groq. AI tự kiểm tra bằng chứng trước khi tạo báo cáo." : "Kiểm tra kết nối backend."}</p></div>
        <small className="sidebar-caption">Paper Review · Local workspace</small>
      </div>
    </aside>
    <div className="workspace">
      <div className="workspace-topbar"><div className="workspace-breadcrumb"><span>Không gian làm việc</span><span aria-hidden="true">/</span><strong>{currentTitle}</strong></div><span className="workspace-local"><span aria-hidden="true"/>Local workspace</span></div>
      <main id="main-content" tabIndex={-1}>{children}</main>
    </div>
  </div>;
}
export function PageHeader({ eyebrow, title, description }: { eyebrow: string; title: string; description: string }) {
  return <header className="page-header"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p>{description}</p></header>;
}
export function ErrorBanner({ message }: { message: string }) {
  return message ? <div role="alert" className="error">{message}</div> : null;
}
