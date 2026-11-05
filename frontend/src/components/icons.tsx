import type { CSSProperties, ReactNode } from "react";

export type IconName = "overview" | "papers" | "rubric" | "review" | "arrow" | "upload" | "check" | "activity";

const paths: Record<IconName, ReactNode> = {
  overview: <><rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/></>,
  papers: <><path d="M4 4.5A1.5 1.5 0 0 1 5.5 3H10a3 3 0 0 1 3 3v15a4 4 0 0 0-4-3H4z"/><path d="M13 6a3 3 0 0 1 3-3h4v15h-3a4 4 0 0 0-4 3"/><path d="M7 7h3M7 10h3M16 7h1"/></>,
  rubric: <><rect x="5" y="5" width="14" height="16" rx="2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="m8 12 1 1 2-2m2 1h3m-8 5 1 1 2-2m2 1h3"/></>,
  review: <><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M14 3v6h6M8 13h8M8 17h5"/></>,
  arrow: <><path d="M5 12h14m-6-6 6 6-6 6"/></>,
  upload: <><path d="M12 16V3m-5 5 5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4"/></>,
  check: <><path d="m6 12 4 4 8-8"/></>,
  activity: <><path d="M3 12h4l3-8 4 16 3-8h4"/></>,
};

export function Icon({ name, size = 20, className, style }: {
  name: IconName; size?: number; className?: string; style?: CSSProperties;
}) {
  return <svg aria-hidden="true" focusable="false" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" className={className} style={style}>{paths[name]}</svg>;
}
