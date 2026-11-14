import type { Metadata } from 'next'
import './globals.css'
import { AppShell } from '@/components/layout/app-shell'
import { QueryProvider } from '@/components/providers/query-provider'

export const metadata: Metadata = {
  title: 'TEAM OBSIDIAN — AI-Powered Knowledge Handover Platform',
  description:
    'Enterprise AI platform preventing organizational brain drain. Reconstructs, verifies, and generates evidence-backed 16-section knowledge handover dossiers.',
  icons: {
    icon: '/favicon.svg',
    shortcut: '/favicon.ico',
    apple: '/apple-icon.png',
  },
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en">
      <body className="bg-[#F8F9FD] text-slate-900 antialiased selection:bg-violet-500/20 selection:text-violet-950">
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  )
}
