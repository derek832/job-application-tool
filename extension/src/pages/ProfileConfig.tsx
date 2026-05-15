import { useState, useEffect, type FormEvent } from "react";
import {
  getUserProfile,
  updateUserProfile,
  type UserProfile,
  ApiError,
} from "../api/client";

type Status = "idle" | "loading" | "saving" | "success" | "error";

interface CommonAnswerEntry {
  key: string;
  value: string;
}

export function ProfileConfig(): React.JSX.Element {
  const [form, setForm] = useState<UserProfile>({
    full_name: null,
    email: null,
    phone: null,
    location: null,
    work_auth: null,
    linkedin_url: null,
    common_answers: {},
  });
  const [commonAnswers, setCommonAnswers] = useState<CommonAnswerEntry[]>([]);
  const [status, setStatus] = useState<Status>("idle");
  const [errorMessage, setErrorMessage] = useState<string>("");

  useEffect(() => {
    let cancelled = false;
    setStatus("loading");
    getUserProfile()
      .then((data) => {
        if (!cancelled) {
          setForm(data);
          setCommonAnswers(
            Object.entries(data.common_answers).map(([key, value]) => ({ key, value }))
          );
          setStatus("idle");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setStatus("error");
          setErrorMessage(err instanceof ApiError ? err.detail : "Failed to load profile.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleChange(field: keyof Omit<UserProfile, "common_answers">, value: string): void {
    setForm((prev) => ({ ...prev, [field]: value || null }));
  }

  function handleAnswerChange(index: number, field: "key" | "value", value: string): void {
    setCommonAnswers((prev) => {
      const updated = [...prev];
      updated[index] = { ...updated[index], [field]: value };
      return updated;
    });
  }

  function addAnswer(): void {
    setCommonAnswers((prev) => [...prev, { key: "", value: "" }]);
  }

  function removeAnswer(index: number): void {
    setCommonAnswers((prev) => prev.filter((_, i) => i !== index));
  }

  function handleSubmit(e: FormEvent): void {
    e.preventDefault();
    setStatus("saving");
    setErrorMessage("");

    const answers: Record<string, string> = {};
    for (const entry of commonAnswers) {
      const trimmedKey = entry.key.trim();
      if (trimmedKey.length > 0) {
        answers[trimmedKey] = entry.value;
      }
    }

    const payload: UserProfile = { ...form, common_answers: answers };
    updateUserProfile(payload)
      .then((saved) => {
        setForm(saved);
        setCommonAnswers(
          Object.entries(saved.common_answers).map(([key, value]) => ({ key, value }))
        );
        setStatus("success");
      })
      .catch((err: unknown) => {
        setStatus("error");
        setErrorMessage(err instanceof ApiError ? err.detail : "Failed to save profile.");
      });
  }

  if (status === "loading") {
    return <div className="p-4 text-gray-500">Loading profile configuration…</div>;
  }

  return (
    <form onSubmit={handleSubmit} className="p-4 space-y-4 max-w-lg">
      <h2 className="text-lg font-semibold text-gray-900">Profile Configuration</h2>

      {status === "error" && (
        <div className="rounded bg-red-50 border border-red-200 p-3 text-sm text-red-700">
          {errorMessage}
        </div>
      )}
      {status === "success" && (
        <div className="rounded bg-green-50 border border-green-200 p-3 text-sm text-green-700">
          Profile saved.
        </div>
      )}

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Full Name</span>
        <input
          type="text"
          value={form.full_name ?? ""}
          onChange={(e) => handleChange("full_name", e.target.value)}
          placeholder="John Doe"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Email</span>
        <input
          type="email"
          value={form.email ?? ""}
          onChange={(e) => handleChange("email", e.target.value)}
          placeholder="john@example.com"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Phone</span>
        <input
          type="tel"
          value={form.phone ?? ""}
          onChange={(e) => handleChange("phone", e.target.value)}
          placeholder="(555) 123-4567"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Location</span>
        <input
          type="text"
          value={form.location ?? ""}
          onChange={(e) => handleChange("location", e.target.value)}
          placeholder="San Francisco, CA"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">Work Authorization</span>
        <input
          type="text"
          value={form.work_auth ?? ""}
          onChange={(e) => handleChange("work_auth", e.target.value)}
          placeholder="e.g. US Citizen, H-1B, Green Card"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <label className="block">
        <span className="text-sm font-medium text-gray-700">LinkedIn URL</span>
        <input
          type="url"
          value={form.linkedin_url ?? ""}
          onChange={(e) => handleChange("linkedin_url", e.target.value)}
          placeholder="https://linkedin.com/in/johndoe"
          className="mt-1 block w-full rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
        />
      </label>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium text-gray-700">Common Application Answers</legend>
        <p className="text-xs text-gray-500">
          Key-value pairs for frequently asked application questions.
        </p>
        {commonAnswers.map((entry, index) => (
          <div key={index} className="flex gap-2 items-start">
            <input
              type="text"
              value={entry.key}
              onChange={(e) => handleAnswerChange(index, "key", e.target.value)}
              placeholder="Question"
              className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            <input
              type="text"
              value={entry.value}
              onChange={(e) => handleAnswerChange(index, "value", e.target.value)}
              placeholder="Answer"
              className="flex-1 rounded border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            />
            <button
              type="button"
              onClick={() => removeAnswer(index)}
              className="rounded px-2 py-2 text-sm text-red-600 hover:bg-red-50"
              aria-label="Remove answer"
            >
              ✕
            </button>
          </div>
        ))}
        <button
          type="button"
          onClick={addAnswer}
          className="rounded border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50"
        >
          + Add Answer
        </button>
      </fieldset>

      <button
        type="submit"
        disabled={status === "saving"}
        className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {status === "saving" ? "Saving…" : "Save"}
      </button>
    </form>
  );
}
