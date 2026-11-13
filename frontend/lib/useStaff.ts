"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "./api";

export type StaffMe = { id: number; name: string; email: string; role: string; two_factor: boolean; lab: { id: number; name: string; sms_sender_id: string | null } };

// Loads the signed-in staff member, or sends them to the login page.
export function useStaff() {
  const router = useRouter();
  const [me, setMe] = useState<StaffMe | null>(null);

  useEffect(() => {
    api<StaffMe>("/api/staff/me")
      .then(setMe)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/staff/login");
      });
  }, [router]);

  async function signOut() {
    await api("/api/staff/logout", { method: "POST" }).catch(() => {});
    router.replace("/staff/login");
  }

  return { me, signOut };
}
