import { NextResponse } from "next/server"
import tls from "node:tls"

export const runtime = "nodejs"
export const dynamic = "force-dynamic"

function sendMailViaTls({
  host,
  port,
  user,
  pass,
  to,
  from,
  subject,
  html,
  text,
}: {
  host: string
  port: number
  user: string
  pass: string
  to: string
  from?: string
  subject: string
  html?: string
  text?: string
}): Promise<{ delivered: boolean; provider: string; messageId: string }> {
  return new Promise((resolve, reject) => {
    const socket = tls.connect({ host, port, rejectUnauthorized: true })
    let buffer = ""
    let state = "CONNECTED"
    const msgId = `<${Date.now()}.${Math.random().toString(36).substring(2, 9)}@teamobsidian.com>`

    socket.setEncoding("utf8")

    function onMultilineComplete(code: string, callback: () => void): boolean {
      const lines = buffer.split("\r\n")
      for (const line of lines) {
        if (line.startsWith(code + " ")) {
          buffer = ""
          callback()
          return true
        }
      }
      return false
    }

    socket.on("data", (chunk: string) => {
      buffer += chunk

      if (state === "CONNECTED") {
        if (
          onMultilineComplete("220", () => {
            state = "EHLO"
            socket.write("EHLO localhost\r\n")
          })
        )
          return
      }
      if (state === "EHLO") {
        if (
          onMultilineComplete("250", () => {
            state = "AUTH"
            socket.write("AUTH LOGIN\r\n")
          })
        )
          return
      }
      if (state === "AUTH") {
        if (buffer.includes("334")) {
          buffer = ""
          state = "USER"
          socket.write(Buffer.from(user).toString("base64") + "\r\n")
          return
        }
      }
      if (state === "USER") {
        if (buffer.includes("334")) {
          buffer = ""
          state = "PASS"
          socket.write(Buffer.from(pass).toString("base64") + "\r\n")
          return
        }
      }
      if (state === "PASS") {
        if (buffer.includes("235")) {
          buffer = ""
          state = "MAIL_FROM"
          socket.write(`MAIL FROM:<${user}>\r\n`)
          return
        }
      }
      if (state === "MAIL_FROM") {
        if (buffer.includes("250")) {
          buffer = ""
          state = "RCPT_TO"
          socket.write(`RCPT TO:<${to}>\r\n`)
          return
        }
      }
      if (state === "RCPT_TO") {
        if (buffer.includes("250")) {
          buffer = ""
          state = "DATA"
          socket.write("DATA\r\n")
          return
        }
      }
      if (state === "DATA") {
        if (buffer.includes("354")) {
          buffer = ""
          state = "BODY"
          const sender = from || `TEAM OBSIDIAN <${user}>`
          const headers = [
            `From: ${sender}`,
            `To: ${to}`,
            `Subject: ${subject}`,
            `Message-ID: ${msgId}`,
            "MIME-Version: 1.0",
            "Content-Type: text/html; charset=UTF-8",
            "Content-Transfer-Encoding: 7bit",
            "",
            html || text,
            "",
            ".",
          ].join("\r\n") + "\r\n"
          socket.write(headers)
          return
        }
      }
      if (state === "BODY") {
        if (buffer.includes("250")) {
          buffer = ""
          state = "DONE"
          socket.write("QUIT\r\n")
          socket.end()
          resolve({ delivered: true, provider: "vercel_smtp_tls", messageId: msgId })
          return
        }
      }
    })

    socket.on("error", (err) => reject(err))
    socket.setTimeout(8000, () => {
      socket.destroy()
      reject(new Error(`SMTP connection timed out at state: ${state}`))
    })
  })
}

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

    const result = await sendMailViaTls({
      host,
      port,
      user,
      pass,
      to,
      from: from || `TEAM OBSIDIAN <${process.env.SMTP_FROM_EMAIL || user}>`,
      subject,
      html,
      text,
    })

    return NextResponse.json(result)
  } catch (error: any) {
    console.error("[MailRelay] Error delivering email via SMTP TLS:", error)
    return NextResponse.json(
      {
        delivered: false,
        error: error.message || "Failed to dispatch email",
      },
      { status: 500 }
    )
  }
}
