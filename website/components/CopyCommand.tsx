"use client";

import { useState } from "react";

function ClipboardIcon() {
  return (
    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none">
      <rect
        x="5.2"
        y="1.6"
        width="5.6"
        height="2.2"
        rx="0.5"
        stroke="currentColor"
        strokeWidth="1.25"
      />
      <rect
        x="3.2"
        y="3.2"
        width="9.6"
        height="11.2"
        rx="1.3"
        stroke="currentColor"
        strokeWidth="1.25"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden="true" width="14" height="14" viewBox="0 0 16 16" fill="none">
      <path
        d="M3.4 8.3 6.6 11.4 12.6 4.6"
        stroke="currentColor"
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export function CopyCommand({ command }: { command: string }) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="command">
      <pre>
        <code>{command}</code>
      </pre>
      <button
        type="button"
        className="command-copy"
        aria-label={copied ? "Copied install command" : "Copy install command"}
        onClick={async () => {
          await navigator.clipboard.writeText(command);
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1600);
        }}
      >
        {copied ? <CheckIcon /> : <ClipboardIcon />}
        <span>{copied ? "Copied" : "Copy"}</span>
      </button>
    </div>
  );
}
