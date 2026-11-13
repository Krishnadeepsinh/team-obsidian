"use client"

import React, { useId } from "react"

export function ProviderLogo({
  provider,
  size = "md",
  className = "",
}: {
  provider: string
  size?: "xs" | "sm" | "md" | "lg"
  className?: string
}) {
  const uid = useId().replace(/:/g, "")
  const key = (provider || "").toLowerCase()

  const boxSizes = {
    xs: "w-5 h-5 rounded-md",
    sm: "w-7 h-7 rounded-lg",
    md: "w-9 h-9 rounded-xl",
    lg: "w-11 h-11 rounded-2xl",
  }[size]

  const svgSizes = {
    xs: "w-3.5 h-3.5",
    sm: "w-4 h-4",
    md: "w-5 h-5",
    lg: "w-6 h-6",
  }[size]

  const bgMap: Record<string, string> = {
    github: "bg-slate-900/5 border-slate-200/90",
    slack: "bg-white border-slate-200/90",
    notion: "bg-white border-slate-200/90",
    jira: "bg-blue-50/70 border-blue-200/70",
    confluence: "bg-sky-50/70 border-blue-200/70",
    linear: "bg-indigo-50/70 border-indigo-200/70",
    gitlab: "bg-orange-50/70 border-orange-200/70",
    sentry: "bg-purple-50/70 border-purple-200/70",
    google_drive: "bg-amber-50/70 border-amber-200/70",
    drive: "bg-amber-50/70 border-amber-200/70",
  }

  const boxStyle = bgMap[key] || "bg-slate-50 border-slate-200"

  const renderSvg = () => {
    switch (key) {
      case "github":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} fill="#181717" aria-hidden="true">
            <path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12" />
          </svg>
        )

      case "slack":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} aria-hidden="true">
            <path
              d="M5.042 15.165a2.528 2.528 0 0 1-2.52 2.523A2.528 2.528 0 0 1 0 15.165a2.527 2.527 0 0 1 2.522-2.52h2.52v2.52zm1.271 0a2.527 2.527 0 0 1 2.521-2.52 2.527 2.527 0 0 1 2.521 2.52v6.313A2.528 2.528 0 0 1 8.834 24a2.528 2.528 0 0 1-2.521-2.522v-6.313z"
              fill="#E01E5A"
            />
            <path
              d="M8.834 5.042a2.528 2.528 0 0 1-2.521-2.52A2.528 2.528 0 0 1 8.834 0a2.528 2.528 0 0 1 2.521 2.522v2.52H8.834zm0 1.271a2.528 2.528 0 0 1 2.521 2.521 2.528 2.528 0 0 1-2.521 2.521H2.522A2.528 2.528 0 0 1 0 8.834a2.528 2.528 0 0 1 2.522-2.521h6.312z"
              fill="#36C5F0"
            />
            <path
              d="M18.956 8.834a2.528 2.528 0 0 1 2.522-2.521A2.528 2.528 0 0 1 24 8.834a2.528 2.528 0 0 1-2.522 2.521h-2.522V8.834zm-1.268 0a2.528 2.528 0 0 1-2.523 2.521 2.527 2.527 0 0 1-2.52-2.521V2.522A2.527 2.527 0 0 1 15.165 0a2.528 2.528 0 0 1 2.523 2.522v6.312z"
              fill="#2EB67D"
            />
            <path
              d="M15.165 18.956a2.528 2.528 0 0 1 2.523 2.522A2.528 2.528 0 0 1 15.165 24a2.527 2.527 0 0 1-2.52-2.522v-2.522h2.52zm0-1.268a2.527 2.527 0 0 1-2.52-2.523 2.526 2.526 0 0 1 2.52-2.52h6.313A2.527 2.527 0 0 1 24 15.165a2.528 2.528 0 0 1-2.522 2.523h-6.313z"
              fill="#ECB22E"
            />
          </svg>
        )

      case "notion":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} fill="#111111" aria-hidden="true">
            <path d="M4.459 4.208c.746.606 1.026.56 2.428.466l13.215-.793c.28 0 .047-.28-.046-.326L17.86 1.968c-.42-.326-.981-.7-2.055-.607L3.01 2.295c-.466.046-.56.28-.374.466zm.793 3.08v13.904c0 .747.373 1.027 1.214.98l14.523-.84c.841-.046.935-.56.935-1.167V6.354c0-.606-.233-.933-.748-.887l-15.177.887c-.56.047-.747.327-.747.934zm14.337.745c.093.42 0 .84-.42.888l-.7.14v10.264c-.608.327-1.168.514-1.635.514-.748 0-.935-.234-1.495-.933l-4.577-7.186v6.952L12.21 19s0 .84-1.168.84l-3.222.186c-.093-.186 0-.653.327-.746l.84-.233V9.854L7.822 9.76c-.094-.42.14-1.026.793-1.073l3.456-.233 4.764 7.279v-6.44l-1.215-.139c-.093-.514.28-.887.747-.933zM1.936 1.035l13.31-.98c1.634-.14 2.055-.047 3.082.7l4.249 2.986c.7.513.934.653.934 1.213v16.378c0 1.026-.373 1.634-1.68 1.726l-15.458.934c-.98.047-1.448-.093-1.962-.747l-3.129-4.06c-.56-.747-.793-1.306-.793-1.96V2.667c0-.839.374-1.54 1.447-1.632z" />
          </svg>
        )

      case "jira":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} aria-hidden="true">
            <defs>
              <linearGradient id={`jira-a-${uid}`} x1="98.03%" y1=".16%" x2="58.89%" y2="40.91%">
                <stop offset="18%" stopColor="#0052CC" />
                <stop offset="100%" stopColor="#2684FF" />
              </linearGradient>
              <linearGradient id={`jira-b-${uid}`} x1="100.67%" y1=".46%" x2="55.4%" y2="44.73%">
                <stop offset="18%" stopColor="#0052CC" />
                <stop offset="100%" stopColor="#2684FF" />
              </linearGradient>
            </defs>
            <path
              d="M23.09 11.17L12.82.9 11.91 0 4.21 7.7.91 11a1.18 1.18 0 0 0 0 1.67l7.01 7.01L11.91 24l7.7-7.7.12-.12 3.36-3.34a1.18 1.18 0 0 0 0-1.67zm-11.18 4.44L8.3 12l3.61-3.61L15.52 12l-3.61 3.61z"
              fill="#2684FF"
            />
            <path
              d="M11.91 8.39A5.97 5.97 0 0 1 11.88 0L4.19 7.69l4.1 4.1 3.62-3.4z"
              fill={`url(#jira-a-${uid})`}
            />
            <path
              d="M15.53 11.99l-3.62 3.62a5.97 5.97 0 0 1 0 8.43l7.7-7.7-4.08-4.35z"
              fill={`url(#jira-b-${uid})`}
            />
          </svg>
        )

      case "confluence":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} aria-hidden="true">
            <defs>
              <linearGradient id={`conf-a-${uid}`} x1="99.1%" y1="15.8%" x2="33.7%" y2="87.8%">
                <stop offset="0%" stopColor="#0052CC" />
                <stop offset="92.3%" stopColor="#2684FF" />
              </linearGradient>
              <linearGradient id={`conf-b-${uid}`} x1=".9%" y1="84.2%" x2="66.3%" y2="12.2%">
                <stop offset="0%" stopColor="#0052CC" />
                <stop offset="92.3%" stopColor="#2684FF" />
              </linearGradient>
            </defs>
            <path
              d="M.87 18.26c-.25.4-.52.87-.75 1.24a.68.68 0 0 0 .23.94l4.41 2.71a.68.68 0 0 0 .95-.22c.19-.32.43-.72.71-1.18 1.88-3.09 3.77-2.71 7.17-1.08l4.38 2.09a.68.68 0 0 0 .92-.34l2.11-4.76a.68.68 0 0 0-.34-.91c-.92-.43-2.75-1.31-4.38-2.09-5.91-2.85-10.94-2.67-15.41 3.6z"
              fill={`url(#conf-a-${uid})`}
            />
            <path
              d="M23.13 5.74c.25-.4.52-.87.75-1.24a.68.68 0 0 0-.23-.94L19.24.85a.68.68 0 0 0-.95.22c-.19.32-.43.72-.71 1.18-1.88 3.09-3.77 2.71-7.17 1.08L6.03 1.24a.68.68 0 0 0-.92.34L3 6.34a.68.68 0 0 0 .34.91c.92.43 2.75 1.31 4.38 2.09 5.91 2.85 10.94 2.67 15.41-3.6z"
              fill={`url(#conf-b-${uid})`}
            />
          </svg>
        )

      case "linear":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} aria-hidden="true">
            <defs>
              <mask id={`linear-mask-${uid}`}>
                <rect width="24" height="24" fill="black" />
                <circle cx="12" cy="12" r="10.5" fill="white" />
                <g transform="rotate(45 12 12)">
                  <rect x="0" y="13.8" width="24" height="1.7" fill="black" />
                  <rect x="0" y="17.2" width="24" height="1.7" fill="black" />
                  <rect x="0" y="20.6" width="24" height="1.7" fill="black" />
                </g>
              </mask>
            </defs>
            <circle cx="12" cy="12" r="10.5" fill="#5E6AD2" mask={`url(#linear-mask-${uid})`} />
          </svg>
        )

      case "gitlab":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} aria-hidden="true">
            <path
              d="M22.646 12.71l-1.26-3.878-2.495-7.676a.635.635 0 0 0-1.209 0l-2.495 7.676H8.813L6.318 1.156a.635.635 0 0 0-1.209 0L2.614 8.832l-1.26 3.878a1.27 1.27 0 0 0 .461 1.42L12 21.525l10.185-7.395a1.27 1.27 0 0 0 .461-1.42z"
              fill="#E24329"
            />
            <path d="M12 21.525l3.187-9.805H8.813L12 21.525z" fill="#E24329" />
            <path d="M12 21.525l-3.187-9.805H4.349L12 21.525z" fill="#FC6D26" />
            <path
              d="M4.349 11.72l-1.26 3.878a1.27 1.27 0 0 0 .461 1.42L12 21.525 4.349 11.72z"
              fill="#FCA326"
            />
            <path
              d="M4.349 11.72h4.464L6.318 4.044a.318.318 0 0 0-.605 0L4.349 11.72z"
              fill="#E24329"
            />
            <path d="M12 21.525l3.187-9.805h4.464L12 21.525z" fill="#FC6D26" />
            <path
              d="M19.651 11.72l1.26 3.878a1.27 1.27 0 0 1-.461 1.42L12 21.525l7.651-9.805z"
              fill="#FCA326"
            />
            <path
              d="M19.651 11.72h-4.464l2.495-7.676a.318.318 0 0 1 .605 0l1.364 7.676z"
              fill="#E24329"
            />
          </svg>
        )

      case "sentry":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} fill="#362D59" aria-hidden="true">
            <path d="M13.91 2.13c-.86-1.49-3-1.49-3.85 0L.22 19.16a2.21 2.21 0 0 0 1.92 3.32h4.1v-2.21H2.14l8.84-15.3c.27-.47.96-.47 1.23 0l1.97 3.41a10.48 10.48 0 0 0-4.96 8.35H7.22v2.21h4.18v1.54a2.21 2.21 0 0 0 2.21 2.21h8.25a2.21 2.21 0 0 0 1.92-3.32L13.91 2.13zm-2.36 16.6A8.29 8.29 0 0 1 15.27 12l2.14 3.7a12.43 12.43 0 0 0-3.8 4.57h-2.06zm4.32 1.54a10.22 10.22 0 0 1 2.91-3.44l3.08 5.34H15.87v-1.9z" />
          </svg>
        )

      case "google_drive":
      case "drive":
        return (
          <svg viewBox="0 0 24 24" className={svgSizes} fill="none" aria-hidden="true">
            <path d="M8.2 3.5h7.6L22.5 15H14.9L8.2 3.5z" fill="#0066DA" />
            <path d="M1.5 15l3.8-6.5L12 20.5H4.4L1.5 15z" fill="#00AC47" />
            <path d="M9.7 15l2.8 5.5h9.5L19.2 15H9.7z" fill="#EA4335" />
          </svg>
        )

      default:
        return (
          <span className="text-[11px] font-bold uppercase text-slate-600">
            {key.slice(0, 2) || "IN"}
          </span>
        )
    }
  }

  return (
    <div
      className={`${boxSizes} border ${boxStyle} flex items-center justify-center flex-shrink-0 ${className}`}
      aria-label={`${provider} logo`}
    >
      {renderSvg()}
    </div>
  )
}
