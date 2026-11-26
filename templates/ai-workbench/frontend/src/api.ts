export interface Channel {base_url: string; model: string; provider: string; key_configured?: boolean; key?: string; clear_key?: boolean; voice?: string; response_format?: string}
export interface Settings {runtime: string; sandbox: string; system_prompt: string; models: Record<string, string>; channels: Record<string, Channel>}
export interface Skill {id: string; name: string}
export interface Module {id: string; name: string; description: string; action_label?: string; fields: {id: string; label: string; type?: string; options?: string[]; placeholder?: string}[]}
export interface Bootstrap {brand: {id: string; name: string; subtitle: string; logo?: string; welcome_title?: string; welcome_subtitle?: string}; navigation?: {id: string; label: string; icon: string}[]; runtimes: {id: string; label: string; available: boolean; protocol: string}[]; skills: Skill[]; modules: Module[]; settings: Settings; capabilities: Record<string, {ready: boolean; supported: boolean; reason: string}>}
export interface Session {id: string; title: string; runtime: string; messages: {role: string; content: string; job: string}[]}
export interface Question {id: string; items: {questionId: string; question: string; options?: {label: string}[]}[]}
export interface Job {id: string; kind: string; state: string; runtime: string; model: string; session_id: string; text: string; error: string; prompt: string; question: Question | null; artifacts: string[]; module_id?: string; activities?: string[]}
export interface Artifact {path: string; name: string; size: number}
export const terminal = new Set(['completed', 'failed', 'cancelled', 'interrupted']);
export async function api<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(path, {method, cache: 'no-store', headers: body === undefined ? {} : {'Content-Type': 'application/json'}, body: body === undefined ? undefined : JSON.stringify(body)});
  if (!response.ok) {const error = await response.json().catch(() => ({})); throw new Error(error.detail || `请求失败（${response.status}）`);}
  return response.json();
}
export async function upload(file: File) {
  const form = new FormData(); form.append('file', file);
  const response = await fetch('/api/uploads', {method: 'POST', body: form});
  const result = await response.json(); if (!response.ok) throw new Error(result.detail || '附件上传失败');
  return result as {id: string; name: string};
}
export const artifactUrl = (path: string) => '/api/artifacts/' + path.split('/').map(encodeURIComponent).join('/');

export const previewUrl = (path: string) => artifactUrl(path) + "?preview=true";
