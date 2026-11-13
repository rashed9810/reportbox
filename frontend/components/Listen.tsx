"use client";

import { useEffect, useState } from "react";

// Reads text aloud with the phone's own voice (Web Speech API). Shown only when the phone has a
// voice for the language, since many Android phones have no Bangla voice installed.
function findVoice(lang: "bn" | "en"): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  return voices.find((v) => v.lang.toLowerCase().startsWith(lang)) || null;
}

export function ListenButton({ text, lang, label, stopLabel }: { text: string; lang: "bn" | "en"; label: string; stopLabel: string }) {
  const [voice, setVoice] = useState<SpeechSynthesisVoice | null>(null);
  const [speaking, setSpeaking] = useState(false);

  useEffect(() => {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const update = () => setVoice(findVoice(lang));
    update();
    window.speechSynthesis.addEventListener("voiceschanged", update);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", update);
      window.speechSynthesis.cancel();
    };
  }, [lang]);

  if (!voice) return null;

  function toggle() {
    const synth = window.speechSynthesis;
    if (speaking) {
      synth.cancel();
      setSpeaking(false);
      return;
    }
    const u = new SpeechSynthesisUtterance(text);
    u.voice = voice;
    u.lang = voice!.lang;
    u.rate = 0.9;
    u.onend = () => setSpeaking(false);
    u.onerror = () => setSpeaking(false);
    synth.cancel();
    synth.speak(u);
    setSpeaking(true);
  }

  return (
    <button type="button" onClick={toggle} aria-pressed={speaking} className="listen-btn">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M11 5L6 9H2v6h4l5 4V5z" />
        {speaking ? <path d="M16 9l5 6M21 9l-5 6" /> : <path d="M15.5 8.5a5 5 0 010 7M19 5a10 10 0 010 14" />}
      </svg>
      {speaking ? stopLabel : label}
    </button>
  );
}
