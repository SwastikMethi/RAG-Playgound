import type {components} from './generated/api';
export type Project = components['schemas']['Project'];
export type Capability = components['schemas']['Capability'];
export type Configuration = components['schemas']['Configuration'];
export type Source = components['schemas']['Source'];
export type Corpus = components['schemas']['Corpus'];
export type Run = components['schemas']['Run'];
export type Lane = components['schemas']['Lane'];
export type Bundle = components['schemas']['IndexBundle'];
export type Pipeline = Configuration['config'];
export type Job = components['schemas']['Job'];

let token = sessionStorage.getItem('rag-token') || '';
export function setToken(value: string) { token=value; value ? sessionStorage.setItem('rag-token',value) : sessionStorage.removeItem('rag-token'); }
export function hasToken() { return !!token; }
export function headers() {return {Authorization:`Bearer ${token}`};}
export async function api<T>(path:string, options:RequestInit={}):Promise<T> {
  const response = await fetch('/api/v1'+path, {...options, headers:{...headers(),
    ...(options.body && !(options.body instanceof FormData) ? {'Content-Type':'application/json'} : {}), ...options.headers}});
  if(!response.ok) {
    const value = await response.json().catch(()=>null);
    throw new Error(value?.error?.message || `Request failed (${response.status}).`);
  }
  return response.status===204 ? undefined as T : response.json();
}
export function post<T>(path:string, body:unknown, idempotent=false) {
  return api<T>(path, {method:'POST', body:JSON.stringify(body),
    headers:idempotent ? {'Idempotency-Key':crypto.randomUUID()} : {}});
}
