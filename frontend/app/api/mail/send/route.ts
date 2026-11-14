import { NextResponse } from "next/server"
import nodemailer from "nodemailer"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

export async function POST(req: Request) {
  try {
    const authHeader = req.headers.get("authorization") || ""
    const expectedSecret = process.env.SECRET_KEY || "35904b1e59cf772ba8bc87296dd833cc0afe474082b70ffcb580893853a08954"

    if (authHeader !== `Bearer ${expectedSecret}`) {
      return NextResponse.json({ error: "Unauthorized mail relay call" }, { status: 401 })
    }

    const body = await req.json()
    const { to, subject, html, text, from } = body

    if (!to || !subject || (!html && !text)) {
      return NextResponse.json({ error: "Missing required mail fields" }, { status: 400 })
    }

    const user = process.env.SMTP_USER || "no.reply.teamobsidian@gmail.com"
    const pass = (process.env.SMTP_PASSWORD || "uvwp qjhj rutu jafs").replace(/\s+/g, "")
    const host = process.env.SMTP_HOST || "smtp.gmail.com"
    const port = Number(process.env.SMTP_PORT) || 465

    const transporter = nodemailer.createTransport({
      host,
      port,
      secure: port === 465,
      auth: {
        user,
        pass,
      },
    })

    const sender = from || `TEAM OBSIDIAN <${process.env.SMTP_FROM_EMAIL || user}>`

    const info = await transporter.sendMail({
      from: sender,
      to,
      subject,
      text: text || "",
      html: html || undefined,
    })

    return NextResponse.json({
      delivered: true,
      provider: "vercel_smtp",
      messageId: info.messageId,
    })
  } catch (error: any) {
    console.error("[MailRelay] Error delivering email via SMTP:", error)
    return NextResponse.json(
      {
        delivered: false,
        error: error.message || "Failed to dispatch email",
      },
      { status: 500 }
    )
  }
}
