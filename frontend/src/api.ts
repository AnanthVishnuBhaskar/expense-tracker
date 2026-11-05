// Typed client for the FastAPI backend. Money arrives as decimal strings.

export type Money = string

export interface TaxLine {
  name: string
  rate_percent: Money | null
  taxable_amount: Money | null
  amount: Money
}

export interface Payment {
  method: string
  card_brand?: string | null
  card_last4?: string | null
  reference?: string | null
  approval_code?: string | null
  amount?: Money | null
}

export interface Extra {
  label: string
  value: string
}

export interface MerchantInfo {
  name: string
  legal_name?: string | null
  branch?: string | null
  address?: string | null
  city?: string | null
  postcode?: string | null
  country?: string | null
  phone?: string | null
  email?: string | null
  website?: string | null
  tax_ids: { type: string; value: string }[]
  registrations: string[]
}

export interface CustomerInfo {
  name?: string | null
  phone?: string | null
  email?: string | null
  billing_address?: string | null
  delivery_address?: string | null
  loyalty_id?: string | null
  tax_id?: string | null
}

export interface LineItem {
  description: string
  description_en?: string | null
  sku?: string | null
  hsn_sac_code?: string | null
  quantity?: Money | null
  unit?: string | null
  unit_price?: Money | null
  discount?: Money | null
  tax_rate_percent?: Money | null
  amount: Money
  category_id?: number | null
}

export interface ExpenseDraft {
  merchant: MerchantInfo
  customer: CustomerInfo
  country?: string | null
  language?: string | null
  document_type?: string | null
  receipt_number?: string | null
  order_number?: string | null
  purchased_on?: string | null
  purchased_at_time?: string | null
  order_type?: string | null
  table_number?: string | null
  guests?: number | null
  cashier?: string | null
  terminal_id?: string | null
  currency: string
  subtotal?: Money | null
  tax_lines: TaxLine[]
  tax_inclusive?: boolean | null
  service_charge?: Money | null
  delivery_fee?: Money | null
  packaging_fee?: Money | null
  tip?: Money | null
  discount_total?: Money | null
  rounding?: Money | null
  total?: Money | null
  amount_tendered?: Money | null
  change_given?: Money | null
  payments: Payment[]
  line_items: LineItem[]
  extras: Extra[]
  warranty_until?: string | null
  return_by?: string | null
  notes?: string | null
  category_id?: number | null
  suggested_category_id?: number | null
  home_currency?: string | null
  fx_rate?: Money | null
  total_home?: Money | null
  low_confidence_fields: string[]
}

export type ReceiptStatus =
  | 'processing'
  | 'ready_to_confirm'
  | 'needs_review'
  | 'retake'
  | 'rejected'
  | 'failed'
  | 'saved'
  | 'discarded'

export interface Receipt {
  id: number
  status: ReceiptStatus
  status_detail: string | null
  issues: string[]
  quality: Record<string, unknown> | null
  draft: ExpenseDraft | null
  confidence: number | null
  duplicate_of_expense_id: number | null
  expense_id: number | null
  already_uploaded: boolean
  uploaded_at: string
  processed_at: string | null
}

export interface Expense {
  id: number
  receipt_id: number | null
  merchant_name: string
  merchant: MerchantInfo | null
  category_id: number | null
  category_name: string | null
  purchased_on: string
  purchased_at_time: string | null
  country: string | null
  currency: string
  total: Money
  tax_total: Money | null
  home_currency: string
  total_home: Money | null
  fx_rate: Money | null
  payment_method: string | null
  receipt_number: string | null
  customer: CustomerInfo
  line_items: LineItem[]
  extras: Extra[]
  notes: string | null
  warranty_until: string | null
  return_by: string | null
  created_at: string
}

export interface Category {
  id: number
  name: string
  icon: string | null
  color: string | null
}

export interface Budget {
  id: number
  category_id: number | null
  amount: Money
}

export interface Settings {
  name: string
  home_currency: string
  home_currency_source: 'default' | 'detected' | 'user'
  timezone: string
  locale: string
}

export interface Insight {
  kind: 'budget' | 'unusual' | 'info'
  severity: 'info' | 'warning' | 'critical'
  message: string
}

export interface MonthSummary {
  month: string
  period: string
  start: string
  end: string
  bucket: 'day' | 'month'
  unconverted: { currency: string; total: Money; count: number }[]
  home_currency: string
  total: Money
  previous_total: Money
  budget: Money | null
  count: number
  by_category: {
    category_id: number | null
    name: string
    color: string | null
    icon: string | null
    spent: Money
    budget: Money | null
    count: number
  }[]
  by_day: { day: string; spent: Money }[]
  top_merchants: { name: string; spent: Money; count: number }[]
  insights: Insight[]
  pending_receipts: number
}

export interface YearOverview {
  year: number
  home_currency: string
  first_month: string | null
  months: { month: string; total: Money; count: number }[]
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init })
  if (res.status === 401 && !path.startsWith('/api/auth/')) {
    window.dispatchEvent(new Event('auth:required'))
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  return res.status === 204 ? (undefined as T) : res.json()
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export interface AuthStatus {
  authenticated: boolean
  name: string | null
  email: string | null
  signup_open: boolean
}

export const api = {
  me: () => request<AuthStatus>('/api/auth/me'),
  login: (body: { email: string; password: string }) =>
    request<AuthStatus>('/api/auth/login', json('POST', body)),
  signup: (body: { name: string; email: string; password: string }) =>
    request<AuthStatus>('/api/auth/signup', json('POST', body)),
  logout: () => request<void>('/api/auth/logout', { method: 'POST' }),
  uploadReceipts(files: File[]) {
    const form = new FormData()
    files.forEach((f) => form.append('files', f))
    return request<Receipt[]>('/api/receipts', { method: 'POST', body: form })
  },
  receipts: (status?: string) =>
    request<Receipt[]>(`/api/receipts${status ? `?status=${status}` : ''}`),
  receipt: (id: number) => request<Receipt>(`/api/receipts/${id}`),
  receiptImageUrl: (id: number) => `/api/receipts/${id}/image`,
  confirm: (id: number, draft: ExpenseDraft) =>
    request<Expense>(`/api/receipts/${id}/confirm`, json('POST', draft)),
  discard: (id: number) => request<Receipt>(`/api/receipts/${id}/discard`, { method: 'POST' }),
  retry: (id: number) => request<Receipt>(`/api/receipts/${id}/retry`, { method: 'POST' }),

  expenses: (params: { month?: string; period?: string; category_id?: number; q?: string } = {}) => {
    const qs = new URLSearchParams()
    Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && qs.set(k, String(v)))
    return request<Expense[]>(`/api/expenses?${qs}`)
  },
  reconvert: () => request<{ converted: number }>('/api/expenses/reconvert', { method: 'POST' }),
  deleteExpense: (id: number) => request<void>(`/api/expenses/${id}`, { method: 'DELETE' }),
  setExpenseCategory: (id: number, categoryId: number) =>
    request<Expense>(`/api/expenses/${id}/category?category_id=${categoryId}`, { method: 'PATCH' }),
  exportUrl: (month?: string, period = 'month') =>
    `/api/expenses/export.csv?period=${period}${month ? `&month=${month}` : ''}`,

  summary: (month: string, period = 'month') =>
    request<MonthSummary>(`/api/summary?month=${month}&period=${period}`),
  yearOverview: (year: number) => request<YearOverview>(`/api/summary/months?year=${year}`),
  categories: () => request<Category[]>('/api/categories'),
  budgets: () => request<Budget[]>('/api/budgets'),
  setBudget: (category_id: number | null, amount: string) =>
    request<Budget>('/api/budgets', json('PUT', { category_id, amount })),
  deleteBudget: (id: number) => request<void>(`/api/budgets/${id}`, { method: 'DELETE' }),
  settings: () => request<Settings>('/api/settings'),
  detectSettings: (body: { timezone: string; locale: string }) =>
    request<Settings>('/api/settings/detect', json('POST', body)),
  updateSettings: (body: Partial<Settings>) => request<Settings>('/api/settings', json('PUT', body)),
}
