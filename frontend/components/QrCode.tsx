"use client";

import QRCode from "qrcode";
import { useEffect, useState } from "react";

// Draws a QR code in the browser, so the link never leaves the phone to be turned into a picture.
export function QrCode({ value, size = 200, label }: { value: string; size?: number; label: string }) {
  const [src, setSrc] = useState("");

  useEffect(() => {
    let cancelled = false;
    QRCode.toDataURL(value, { width: size * 2, margin: 1, errorCorrectionLevel: "M" })
      .then((url) => !cancelled && setSrc(url))
      .catch(() => setSrc(""));
    return () => {
      cancelled = true;
    };
  }, [value, size]);

  if (!src) return null;
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} width={size} height={size} alt={label} style={{ display: "block", background: "#fff", borderRadius: 8 }} />;
}
