/**
 * 脱敏批次「复读」与正式交付闸门的数据层。
 *
 * 这里的归一化函数刻意宽松：除了识别本仓库后端的标准结构，也兼容
 * batchId / sample 等常见别名字段。复读响应的批次身份用于把交错返回的
 * 结果精确贴回对应批次行，绝不按“最后一次请求”整体覆盖。
 */
import { request } from './client'

export type AppliesTo = {
  batch_id: number | null
  batch_no: string
  sample_code: string
  version: string
}

export type RereadReceipt = {
  id: number | null
  receipt_no: string
  batch_id: number | null
  batch_no: string
  sample_code: string
  version: string
  readable: boolean
  result: string
  message: string
  missing_fields: string[]
  matched_fields: string[]
  created_at: string
  applies_to: AppliesTo | null
  eligible: boolean
}

export type MaskBatch = {
  id: number
  batch_no: string
  sample_code: string
  version: string
  status: string
  eligible: boolean
  delivery_status: string
  eligibility_message: string
  receipts: RereadReceipt[]
  receipt_count?: number
  latest_receipt: RereadReceipt | null
  submitted_at?: string
  rule_no?: string
  watermark_no?: string
  output_text?: string
}

export type RereadState = {
  batches: MaskBatch[]
  receipts: RereadReceipt[]
  sample_groups: SampleGroup[]
}

export type SampleGroup = {
  sample_code: string
  latest_batch_id: number
  latest_version: string
  batch_ids: number[]
  deliverable_batch_ids: number[]
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {}
}

function pick(value: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (value[key] !== undefined && value[key] !== null) return value[key]
  }
  // 大小写/下划线不敏感兜底。
  const lower = new Map(Object.keys(value).map((k) => [k.toLowerCase().replace(/[-_]/g, ''), k]))
  for (const key of keys) {
    const hit = lower.get(key.toLowerCase().replace(/[-_]/g, ''))
    if (hit && value[hit] !== undefined && value[hit] !== null) return value[hit]
  }
  return undefined
}

function toNumber(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) {
    return Number(value)
  }
  return null
}

function asString(value: unknown, fallback = ''): string {
  if (value === undefined || value === null) return fallback
  return typeof value === 'string' ? value : String(value)
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => asString(item)).filter(Boolean)
  if (typeof value === 'string' && value.trim()) return [value]
  return []
}

function asBool(value: unknown): boolean | null {
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return value !== 0
  if (typeof value === 'string') {
    const text = value.trim().toLowerCase()
    if (['true', '1', 'yes', 'pass', 'passed', '通过', '可读'].includes(text)) return true
    if (['false', '0', 'no', 'fail', 'failed', '未通过', '不可读'].includes(text)) return false
  }
  return null
}

/** 把任意复读响应体归一化为回执；requestedBatchId 是请求闭包捕获的批次身份。 */
export function normalizeReceipt(raw: unknown, requestedBatchId: number): RereadReceipt {
  const root = asRecord(raw)
  const nested = asRecord(pick(root, ['receipt', 'entry', 'data']))
  const source = Object.keys(nested).length ? { ...root, ...nested } : root

  const appliesRaw = asRecord(pick(source, ['applies_to', 'appliesTo', 'scope']))
  const batchId = toNumber(pick(source, ['batch_id', 'batchId', 'batchID', 'batch', '批次ID']))
    ?? toNumber(pick(appliesRaw, ['batch_id', 'batchId', 'id']))
    ?? requestedBatchId
  const sampleCode = asString(pick(source, ['sample_code', 'sampleCode', 'sample', '样本编号']))
    || asString(pick(appliesRaw, ['sample_code', 'sampleCode']))
  const version = asString(pick(source, ['version', 'process_version', 'processVersion', '处理版本']))
    || asString(pick(appliesRaw, ['version']))
  const readable = asBool(pick(source, ['readable', 'detected', 'watermark_readable', 'has_watermark']))
  const resultText = asString(pick(source, ['result', 'status_text', '结论']))
  const okFlag = asBool(pick(source, ['ok', 'success']))
  const isReadable = readable
    ?? (resultText ? /通过|可辨认|可读|pass|ok/i.test(resultText) && !/未通过|不可读/.test(resultText) : null)
    ?? okFlag
    ?? false

  return {
    id: toNumber(pick(source, ['id', 'receipt_id', 'receiptId'])) ?? toNumber(pick(root, ['receipt_id'])),
    receipt_no: asString(pick(source, ['receipt_no', 'receiptNo', 'receipt_code', '编号'])),
    batch_id: batchId,
    batch_no: asString(pick(source, ['batch_no', 'batchNo', 'batch_code', '批次编号'])),
    sample_code: sampleCode,
    version,
    readable: isReadable,
    result: resultText || (isReadable ? '通过' : '未通过'),
    message: asString(pick(source, ['message', 'detail', 'msg']))
      || (isReadable ? '复读通过：输出样本中的水印仍可辨认。' : '复读未通过：输出中没有可读水印。'),
    missing_fields: asStringList(pick(source, ['missing_fields', 'missingFields'])),
    matched_fields: asStringList(pick(source, ['matched_fields', 'matchedFields'])),
    created_at: asString(pick(source, ['created_at', 'createdAt', 'time'])),
    applies_to: Object.keys(appliesRaw).length
      ? {
          batch_id: toNumber(pick(appliesRaw, ['batch_id', 'batchId'])) ?? batchId,
          batch_no: asString(pick(appliesRaw, ['batch_no', 'batchNo'])),
          sample_code: asString(pick(appliesRaw, ['sample_code', 'sampleCode'])) || sampleCode,
          version: asString(pick(appliesRaw, ['version'])) || version,
        }
      : { batch_id: batchId, batch_no: '', sample_code: sampleCode, version },
    eligible: asBool(pick(source, ['eligible', 'deliverable'])) ?? isReadable,
  }
}

export function normalizeBatch(raw: unknown): MaskBatch {
  const b = asRecord(raw)
  const id = toNumber(pick(b, ['id', 'batch_id', 'batchId'])) ?? 0
  const receiptsRaw = pick(b, ['receipts', 'reread_receipts'])
  const receipts = Array.isArray(receiptsRaw)
    ? receiptsRaw.map((r) => normalizeReceipt(r, id))
    : []
  const latestRaw = pick(b, ['latest_receipt', 'latestReceipt'])
  const latest = latestRaw ? normalizeReceipt(latestRaw, id) : (receipts.at(-1) ?? null)
  const eligible = asBool(pick(b, ['eligible', 'deliverable']))
    ?? receipts.some((r) => r.readable)
  return {
    id,
    batch_no: asString(pick(b, ['batch_no', 'batchNo', 'batch_code']), `BATCH-${id}`),
    sample_code: asString(pick(b, ['sample_code', 'sampleCode', 'sample'])),
    version: asString(pick(b, ['version', 'process_version', 'processVersion'])),
    status: asString(pick(b, ['status', 'reread_status']), '待复读'),
    eligible,
    delivery_status: asString(pick(b, ['delivery_status', 'deliveryStatus']))
      || (eligible ? '可正式交付' : latest ? '复读未通过·禁止正式交付' : '待复读·交付未解锁'),
    eligibility_message: asString(pick(b, ['eligibility_message', 'eligibilityMessage']), ''),
    receipts,
    latest_receipt: latest,
    submitted_at: asString(pick(b, ['submitted_at', 'submittedAt'])),
    rule_no: asString(pick(b, ['rule_no', 'ruleNo'])),
    watermark_no: asString(pick(b, ['watermark_no', 'watermarkNo'])),
    output_text: asString(pick(b, ['output_text', 'outputText'])),
  }
}

export async function fetchRereadState(): Promise<RereadState> {
  const response = await request('/api/reread/state')
  if (!response.ok) throw new Error('复读记录读取失败')
  const json = await response.json() as Record<string, unknown>
  const batchList = (pick(json, ['batches', 'items']) as unknown[]) ?? []
  const receiptList = (pick(json, ['receipts']) as unknown[]) ?? []
  const batches = (Array.isArray(batchList) ? batchList : []).map(normalizeBatch)
  const receipts = (Array.isArray(receiptList) ? receiptList : [])
    .map((r) => normalizeReceipt(r, toNumber(asRecord(r).batch_id) ?? 0))
  const groupsRaw = pick(json, ['sample_groups', 'sampleGroups'])
  const sample_groups: SampleGroup[] = Array.isArray(groupsRaw)
    ? (groupsRaw as Record<string, unknown>[]).map((g) => ({
        sample_code: asString(pick(g, ['sample_code', 'sampleCode'])),
        latest_batch_id: toNumber(pick(g, ['latest_batch_id', 'latestBatchId'])) ?? 0,
        latest_version: asString(pick(g, ['latest_version', 'latestVersion'])),
        batch_ids: asNumberList(pick(g, ['batch_ids', 'batchIds'])),
        deliverable_batch_ids: asNumberList(pick(g, ['deliverable_batch_ids', 'deliverableBatchIds'])),
      }))
    : []
  return { batches, receipts, sample_groups }
}

function asNumberList(value: unknown): number[] {
  return Array.isArray(value) ? value.map(toNumber).filter((n): n is number => n !== null) : []
}

export type BatchInput = {
  sample_code: string
  version: string
  watermark_no?: string
  output: unknown
  auto_reread?: boolean
}

export async function submitMaskBatch(input: BatchInput): Promise<{ batch: MaskBatch; receipt: RereadReceipt | null; raw: unknown }> {
  const response = await request('/api/mask-batches', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  const json = await response.json().catch(() => ({})) as Record<string, unknown>
  if (!response.ok || json.ok === false) {
    throw new Error(asString(pick(json, ['message', 'detail']), '脱敏批次提交失败'))
  }
  const batchRaw = pick(json, ['batch', 'entry']) ?? json
  const batch = normalizeBatch(batchRaw)
  const receiptRaw = pick(json, ['receipt'])
  const receipt = receiptRaw ? normalizeReceipt(receiptRaw, batch.id) : null
  if (receipt && !batch.latest_receipt) batch.latest_receipt = receipt
  if (receipt?.readable) batch.eligible = true
  return { batch, receipt, raw: json }
}

/**
 * 发起复读。注意：每个调用都在闭包里捕获自己的 requestedBatchId，
 * 响应回来后又以响应中的 batch_id（缺失时回退到请求 id）定位行，
 * 因此两次复读即使交错返回也不会把结论贴错批次。
 */
export async function rereadBatch(
  requestedBatchId: number,
): Promise<{ receipt: RereadReceipt; batch: MaskBatch | null; raw: unknown }> {
  const response = await request(`/api/mask-batches/${requestedBatchId}/reread`, {
    method: 'POST',
    body: JSON.stringify({}),
  })
  const json = await response.json().catch(() => ({})) as Record<string, unknown>
  if (!response.ok) {
    throw new Error(asString(pick(json, ['message', 'detail']), '复读请求失败'))
  }
  const receipt = normalizeReceipt(pick(json, ['receipt']) ?? json, requestedBatchId)
  // 双保险：服务端/模拟响应若没带对身份，仍然只更新请求发出的那一行。
  if (receipt.batch_id === null || receipt.batch_id === undefined) {
    receipt.batch_id = requestedBatchId
  }
  const batchRaw = pick(json, ['batch'])
  const batch = batchRaw ? normalizeBatch(batchRaw) : null
  return { receipt, batch, raw: json }
}

export function deliveryUrl(batchId: number): string {
  return `/api/mask-batches/${batchId}/delivery`
}
