"use client";

export interface ChatHit {
  id: string;
  summary: string;
  why: string;
  tier: string;
}

export interface ChatMsg {
  role: "user" | "tottie";
  text: string;
  card?: string | null;
  confidence?: number;
  abstain?: boolean;
  story?: string | null;
}

export default function Chat({
  messages,
  onSend,
  busy,
}: {
  messages: ChatMsg[];
  onSend: (text: string) => void;
  busy: boolean;
}) {
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("q") as HTMLInputElement;
    const v = input.value.trim();
    if (!v || busy) return;
    input.value = "";
    onSend(v);
  };
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto space-y-3 pr-1">
        {messages.length === 0 && (
          <p className="dim text-sm">
            Say something worth remembering. Watch the Panel learn it live.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
            <div
              className={`inline-block max-w-[92%] text-left px-3 py-2 ${
                m.role === "user" ? "card" : ""
              }`}
              style={m.role === "tottie" ? { borderLeft: "2px solid #2a2a33", paddingLeft: "0.75rem" } : undefined}
            >
              <p className="text-[0.95rem] whitespace-pre-wrap">{m.text}</p>
              {m.role === "tottie" && m.card != null && (
                <details className="mt-1 text-xs dim">
                  <summary className="cursor-pointer">
                    context card · conf {m.confidence?.toFixed(2)}
                    {m.abstain ? " · abstained" : ""}
                  </summary>
                  <pre className="mono whitespace-pre-wrap mt-1">{m.card}</pre>
                </details>
              )}
              {m.role === "tottie" && m.story != null && (
                <div className="mono text-xs dim mt-1">
                  why this surfaced → {m.story}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          name="q"
          autoComplete="off"
          placeholder={busy ? "thinking…" : "message Tottie"}
          disabled={busy}
          className="card flex-1 px-3 py-2 text-[0.95rem] bg-transparent outline-none"
        />
        <button type="submit" disabled={busy} className="action">
          send
        </button>
      </form>
    </div>
  );
}
