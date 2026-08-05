"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { api, ApiError } from "@/lib/api";
import { useApi } from "@/lib/useApi";
import type { AdminUser, Factory } from "@/lib/types";

type Role = AdminUser["role"];
const ROLES: Role[] = ["factory_user", "analyst", "admin"];

function roleLabel(t: ReturnType<typeof useTranslations>, role: Role): string {
  return t(`role_${role}`);
}

export default function AdminUsersPage() {
  const t = useTranslations("admin");
  const { data, loading, reload } = useApi<AdminUser[]>("/admin/users");
  const { data: factories } = useApi<Factory[]>("/admin/factories");
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const factoryName = useMemo(() => {
    const map = new Map<string, string>();
    (factories ?? []).forEach((f) => map.set(f.id, f.name_en));
    return map;
  }, [factories]);

  const users = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = data ?? [];
    if (!q) return rows;
    return rows.filter(
      (u) => u.email.toLowerCase().includes(q) || (u.full_name ?? "").toLowerCase().includes(q),
    );
  }, [data, query]);

  async function setActive(user: AdminUser, active: boolean) {
    setBusyId(user.id);
    setNotice(null);
    try {
      await api.post(`/admin/users/${user.id}/${active ? "activate" : "deactivate"}`);
      await reload();
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  }

  async function resetPassword(user: AdminUser) {
    setBusyId(user.id);
    setNotice(null);
    try {
      await api.post(`/admin/users/${user.id}/reset-password`);
      setNotice(t("resetSent", { email: user.email }));
    } catch (err) {
      setNotice(err instanceof ApiError ? err.message : t("actionError"));
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between gap-3">
        <h1 className="text-2xl font-bold text-gray-900">{t("users")}</h1>
        <button
          onClick={() => {
            setNotice(null);
            setOpen(true);
          }}
          className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700"
        >
          {t("addUser")}
        </button>
      </div>

      {notice && (
        <div
          role="status"
          className="mt-4 rounded-lg bg-green-50 px-4 py-3 text-sm text-green-800 ring-1 ring-green-200"
        >
          {notice}
        </div>
      )}

      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder={t("searchUsers")}
        className="mt-4 w-full max-w-sm rounded-lg border border-gray-300 px-3 py-2 text-sm text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
      />

      {loading ? (
        <p className="mt-6 text-gray-400">…</p>
      ) : users.length === 0 ? (
        <p className="mt-6 rounded-xl bg-white p-8 text-center text-gray-500 ring-1 ring-black/5">
          {t("noUsers")}
        </p>
      ) : (
        <ul className="mt-4 space-y-2">
          {users.map((u) => (
            <li
              key={u.id}
              className="rounded-xl bg-white p-4 shadow-sm ring-1 ring-black/5"
              data-testid="user-row"
            >
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate font-medium text-gray-900" dir="ltr">
                    {u.email}
                  </p>
                  <p className="text-xs text-gray-500">
                    {u.full_name ? `${u.full_name} · ` : ""}
                    {roleLabel(t, u.role)}
                    {u.factory_id ? ` · ${factoryName.get(u.factory_id) ?? ""}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                      u.is_active ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                    }`}
                  >
                    {u.is_active ? t("active") : t("inactive")}
                  </span>
                  <button
                    onClick={() => setActive(u, !u.is_active)}
                    disabled={busyId === u.id}
                    className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
                  >
                    {u.is_active ? t("deactivate") : t("activate")}
                  </button>
                  <button
                    onClick={() => resetPassword(u)}
                    disabled={busyId === u.id}
                    className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
                  >
                    {t("resetPassword")}
                  </button>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}

      {open && (
        <CreateUserDialog
          factories={factories ?? []}
          onClose={() => setOpen(false)}
          onCreated={() => {
            setOpen(false);
            setNotice(t("userCreated"));
            reload();
          }}
        />
      )}
    </div>
  );
}

function CreateUserDialog({
  factories,
  onClose,
  onCreated,
}: {
  factories: Factory[];
  onClose: () => void;
  onCreated: () => void;
}) {
  const t = useTranslations("admin");
  const [email, setEmail] = useState("");
  const [fullName, setFullName] = useState("");
  const [role, setRole] = useState<Role>("factory_user");
  const [factoryId, setFactoryId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsFactory = role === "factory_user";

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (needsFactory && !factoryId) {
      setError(t("factoryRequired"));
      return;
    }
    setBusy(true);
    try {
      await api.post("/admin/users", {
        email,
        full_name: fullName || null,
        role,
        factory_id: needsFactory ? factoryId : null,
      });
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("createError"));
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-20 grid place-items-center bg-black/30 px-4" onClick={onClose}>
      <form
        onSubmit={submit}
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-md space-y-3 rounded-2xl bg-white p-6 shadow-lg"
      >
        <h2 className="text-lg font-bold text-gray-900">{t("addUser")}</h2>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("email")}</span>
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            dir="ltr"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("fullName")}</span>
          <input
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-gray-700">{t("role")}</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {roleLabel(t, r)}
              </option>
            ))}
          </select>
        </label>
        {needsFactory && (
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-gray-700">{t("factory")}</span>
            <select
              value={factoryId}
              onChange={(e) => setFactoryId(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-start outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            >
              <option value="">{t("selectFactory")}</option>
              {factories.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name_en}
                </option>
              ))}
            </select>
          </label>
        )}
        {error && (
          <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-60"
          >
            {t("cancel")}
          </button>
          <button
            type="submit"
            disabled={busy}
            className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60"
          >
            {t("create")}
          </button>
        </div>
      </form>
    </div>
  );
}
