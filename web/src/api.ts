// src/api.ts — thin fetch wrapper for app/api.py.
//
// NUMERIC COERCION NOTE (this codebase's real analogue of the VLS
// bigint-string bug): app/api.py's `id` fields are native Python ints
// (psycopg2 maps Postgres BIGINT -> Python int, and pydantic's `id: int`
// serializes as a real JSON number) — unlike VLS's Node/node-postgres
// backend, ids do NOT come back as strings here, so no Number() coercion
// is needed for ids specifically.
//
// The actual landmine in THIS backend is Decimal money fields
// (gross_revenue, direct_ro_costs, labor_cost, rent_utility_share,
// net_profit, amount, total_collected, etc.) — pydantic serializes
// `Decimal` as a JSON STRING by default (e.g. "1500.00", not 1500.00),
// to avoid float precision loss. Every type below therefore types those
// fields as `string`, and every place this app does arithmetic on them
// (sums, comparisons) MUST go through `money()` below rather than
// assuming the JSON body already gave it a number — the same class of
// bug as VLS's CaseListPage, just triggered by a different serialization
// boundary (Decimal-as-string vs bigint-as-string).
const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

export class ApiError extends Error {
  status: number;
  body: any;
  constructor(status: number, body: any) {
    super(body?.detail ?? `API error ${status}`);
    this.status = status;
    this.body = body;
  }
}

export function money(v: string | number | null | undefined): number {
  if (v === null || v === undefined) return 0;
  return typeof v === 'number' ? v : parseFloat(v);
}

export function fmtMoney(v: string | number | null | undefined): string {
  return money(v).toLocaleString('en-US', { style: 'currency', currency: 'USD' });
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  };
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new ApiError(res.status, body);
  return body as T;
}

// ---------------------------------------------------------------------------
// Typed shapes — matching app/api.py's pydantic response_models 1:1.
// ---------------------------------------------------------------------------

export type JobCategory = 'collision' | 'pdr' | 'hail';
export type JobStatus =
  | 'undecided' | 'came_in' | 'estimate' | 'teardown' | 'waiting_on_parts'
  | 'bodywork' | 'paint' | 'detail' | 'delivered' | 'closed_out' | 'marketing';
export type CostCategory = 'parts' | 'labor' | 'paint_materials' | 'sublet' | 'rental_reimbursement' | 'other';
export type StaffRole = 'owner' | 'manager' | 'receptionist';
export type PaymentSource = 'authorize_net' | 'check' | 'insurer_eft' | 'manual';

export const JOB_STATUS_SEQUENCE: JobStatus[] = [
  'undecided', 'came_in', 'estimate', 'teardown', 'waiting_on_parts',
  'bodywork', 'paint', 'detail', 'delivered', 'closed_out', 'marketing',
];

export interface RepairOrder {
  id: number;
  ro_number: string;
  vehicle_id: number;
  customer_id: number;
  site_id: number;
  category: JobCategory;
  status: JobStatus;
  claim_number: string | null;
  insurer: string | null;
  adjuster_name: string | null;
  posture: string | null;
  gross_revenue: string;
  direct_ro_costs: string;
  labor_cost: string;
  rent_utility_share: string;
  net_profit: string;
}

export interface JobEvent {
  id: number;
  job_id: number;
  from_status: JobStatus | null;
  to_status: JobStatus;
  created_by: string | null;
  note: string | null;
}

export interface CostEntry {
  id: number;
  job_id: number;
  category: CostCategory;
  description: string | null;
  amount: string;
  incurred_at: string | null;
  source: string;
  source_file: string | null;
}

export interface Estimate {
  id: number;
  job_id: number;
  version: number;
  source: string;
  draft_content: Record<string, unknown> | null;
  confirmed_content: Record<string, unknown> | null;
  confirmed_by: string | null;
}

export interface Payment {
  id: number;
  job_id: number;
  source: PaymentSource;
  external_transaction_id: string | null;
  amount: string;
  received_at: string;
  accounting_sync_ref: string | null;
}

export interface JobPaymentSummary {
  job_id: number;
  ro_number: string;
  total_collected: string;
  payment_count: number;
  last_payment_at: string | null;
}

export interface Site {
  id: number;
  name: string;
  address: string | null;
  active: boolean;
}

export interface StaffUser {
  id: number;
  person_id: number;
  role: StaffRole;
  google_email: string;
  active: boolean;
  provisioned_by_staff_user_id: number | null;
}

export interface Customer {
  id: number;
  person_id: number;
  source: string;
  elektrica_renter_ref: number | null;
}

export interface Vehicle {
  id: number;
  vin: string | null;
  make: string | null;
  model: string | null;
  year: number | null;
  customer_id: number;
}

export interface CategorySettlement {
  category: JobCategory;
  ro_numbers: string[];
  gross_revenue: string;
  total_costs_netted: string;
  net_profit: string;
  cc_share_amount: string;
  pdr_share_amount: string;
}

export interface MonthlySettlement {
  month: string;
  site: string;
  status: string;
  total_owed_to_pdr: string;
  categories: CategorySettlement[];
  statement_text: string;
}

export interface PersonPreview {
  id: number;
  first_name: string | null;
  last_name: string | null;
  email_normalized: string | null;
  phone_normalized: string | null;
}

// Customer intake (POST /customers/intake) — the real identity-resolution
// path via platform.match_or_create_person(), added this cycle. Mirrors
// app/api.py's CustomerIntakeRequest/CustomerIntakeOut 1:1.
export interface CustomerIntakeRequest {
  first_name: string;
  last_name: string;
  actor: string;
  date_of_birth?: string; // YYYY-MM-DD
  email?: string;
  phone?: string;
  source?: string; // defaults server-side to 'walk_in'
}

export interface CustomerIntakeResult {
  match_status: 'attached' | 'created' | 'queued';
  person_id: number;
  queue_id: number | null;
  customer: Customer | null;
}

// Staff intake (POST /staff/intake) — mirrors CustomerIntakeRequest/Result
// above, matching app/api.py's StaffIntakeRequest/StaffIntakeOut 1:1.
// google_email is always the COMPANY address (written to
// collision.staff_user regardless of match outcome); personal_email/
// personal_phone/date_of_birth are the new hire's PERSONAL contact info,
// used only for platform.person identity matching (see app/api.py's
// StaffIntakeRequest docstring) — do NOT pass google_email as
// personal_email, it will never match anything.
export interface StaffIntakeRequest {
  first_name: string;
  last_name: string;
  role: StaffRole;
  google_email: string;
  actor: string;
  date_of_birth?: string; // YYYY-MM-DD
  personal_email?: string;
  personal_phone?: string;
  provisioned_by_staff_user_id?: number;
}

export interface StaffIntakeResult {
  match_status: 'attached' | 'created' | 'queued';
  person_id: number;
  queue_id: number | null;
  staff: StaffUser | null;
}

export const api = {
  apiFetchPerson: (personId: string | number) => apiFetch<PersonPreview>(`/persons/${personId}`),

  // Jobs / repair orders
  listJobs: (params: { status?: string; category?: string; site_id?: number; limit?: number; offset?: number } = {}) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => { if (v !== undefined && v !== '') qs.set(k, String(v)); });
    return apiFetch<RepairOrder[]>(`/jobs?${qs.toString()}`);
  },
  getJob: (roNumber: string) => apiFetch<RepairOrder>(`/jobs/${encodeURIComponent(roNumber)}`),
  createJob: (body: Record<string, unknown>) =>
    apiFetch<RepairOrder>('/jobs', { method: 'POST', body: JSON.stringify(body) }),
  patchJobIntake: (roNumber: string, body: Record<string, unknown>) =>
    apiFetch<RepairOrder>(`/jobs/${encodeURIComponent(roNumber)}`, { method: 'PATCH', body: JSON.stringify(body) }),
  transitionJob: (roNumber: string, body: { target_status: JobStatus; actor: string; note?: string }) =>
    apiFetch<RepairOrder>(`/jobs/${encodeURIComponent(roNumber)}/transition`, { method: 'POST', body: JSON.stringify(body) }),
  getJobEvents: (roNumber: string) => apiFetch<JobEvent[]>(`/jobs/${encodeURIComponent(roNumber)}/events`),

  // Cost entries
  getJobCosts: (roNumber: string) => apiFetch<CostEntry[]>(`/jobs/${encodeURIComponent(roNumber)}/costs`),
  addJobCost: (roNumber: string, body: { category: CostCategory; amount: string; actor: string; description?: string; incurred_at?: string }) =>
    apiFetch<CostEntry>(`/jobs/${encodeURIComponent(roNumber)}/costs`, { method: 'POST', body: JSON.stringify(body) }),

  // Estimates
  getJobEstimates: (roNumber: string) => apiFetch<Estimate[]>(`/jobs/${encodeURIComponent(roNumber)}/estimates`),
  createJobEstimate: (roNumber: string, body: { content: Record<string, unknown>; actor: string }) =>
    apiFetch<Estimate>(`/jobs/${encodeURIComponent(roNumber)}/estimates`, { method: 'POST', body: JSON.stringify(body) }),

  // Payments
  getJobPayments: (roNumber: string) => apiFetch<Payment[]>(`/jobs/${encodeURIComponent(roNumber)}/payments`),
  getJobPaymentsSummary: (roNumber: string) =>
    apiFetch<JobPaymentSummary>(`/jobs/${encodeURIComponent(roNumber)}/payments/summary`).catch((e) => {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    }),
  addJobPayment: (roNumber: string, body: { source: PaymentSource; amount: string; actor: string; external_transaction_id?: string; accounting_sync_ref?: string }) =>
    apiFetch<Payment>(`/jobs/${encodeURIComponent(roNumber)}/payments`, { method: 'POST', body: JSON.stringify(body) }),

  // Sites
  listSites: (activeOnly = false) => apiFetch<Site[]>(`/sites?active_only=${activeOnly}`),

  // Customers / vehicles
  getCustomer: (customerId: number) => apiFetch<Customer>(`/customers/${customerId}`),
  getCustomerVehicles: (customerId: number) => apiFetch<Vehicle[]>(`/customers/${customerId}/vehicles`),

  // Staff
  listStaff: (activeOnly = false) => apiFetch<StaffUser[]>(`/staff?active_only=${activeOnly}`),
  getStaffByEmail: (email: string) => apiFetch<StaffUser>(`/staff/${encodeURIComponent(email)}`),
  provisionStaff: (body: { person_id: number; role: StaffRole; google_email: string; actor: string }) =>
    apiFetch<StaffUser>('/staff', { method: 'POST', body: JSON.stringify(body) }),
  setStaffActive: (email: string, body: { active: boolean; actor: string }) =>
    apiFetch<StaffUser>(`/staff/${encodeURIComponent(email)}/active`, { method: 'POST', body: JSON.stringify(body) }),

  // PDR Crew settlement (read-only draft calculator)
  getPdrSettlement: (siteId: number, month: string) =>
    apiFetch<MonthlySettlement>(`/settlements/pdr-crew?site_id=${siteId}&month=${encodeURIComponent(month)}`),

  // Customer intake (new/returning customer identity resolution)
  intakeCustomer: (body: CustomerIntakeRequest) =>
    apiFetch<CustomerIntakeResult>('/customers/intake', { method: 'POST', body: JSON.stringify(body) }),

  // Staff intake (new-hire identity resolution; onboards via personal
  // contact info instead of requiring an already-known person_id)
  intakeStaff: (body: StaffIntakeRequest) =>
    apiFetch<StaffIntakeResult>('/staff/intake', { method: 'POST', body: JSON.stringify(body) }),
};
